#!/usr/bin/env python3
"""Run the TelcoMind offline test matrix with component isolation."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


REQUIRED_FIELDS = {
    "id",
    "description",
    "working_directory",
    "runner",
    "args",
    "category",
    "required",
    "fast",
    "requires_docker",
    "requires_running_stack",
    "timeout_seconds",
    "junit_output",
    "isolation_reason",
    "environment",
    "forbidden_network",
}
OFFLINE_PROXY_ENV = {
    "HTTP_PROXY": "http://127.0.0.1:9",
    "HTTPS_PROXY": "http://127.0.0.1:9",
    "ALL_PROXY": "http://127.0.0.1:9",
    "NO_PROXY": "127.0.0.1,localhost,::1,testserver",
    "PIP_NO_INDEX": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    "PYTHONDONTWRITEBYTECODE": "1",
}
SUMMARY_RE = re.compile(
    r"=+\s*(?:(?P<failed>\d+) failed,\s*)?(?:(?P<passed>\d+) passed)?"
    r"(?:,\s*(?P<skipped>\d+) skipped)?(?:,\s*(?P<warnings>\d+) warnings?)?.*=+"
)
PYTHON_CANDIDATES_POSIX = [
    Path("CODE/.venv/bin/python"),
    Path(".venv/bin/python"),
    Path("venv/bin/python"),
]
PYTHON_CANDIDATES_WINDOWS = [
    Path("CODE/.venv/Scripts/python.exe"),
    Path(".venv/Scripts/python.exe"),
    Path("venv/Scripts/python.exe"),
]


class MatrixError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def find_repo_root(start: Path) -> Path:
    for path in [start.resolve(), *start.resolve().parents]:
        if (path / "tests" / "test_matrix.json").exists() and (path / "docker-compose.yml").exists():
            return path
    raise MatrixError("Could not locate repository root containing tests/test_matrix.json.")


def relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load_matrix(root: Path) -> dict[str, Any]:
    matrix_path = root / "tests" / "test_matrix.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    if not isinstance(matrix.get("suites"), list) or not matrix["suites"]:
        raise MatrixError("test matrix must contain a non-empty suites list")
    seen: set[str] = set()
    for suite in matrix["suites"]:
        missing = sorted(REQUIRED_FIELDS - set(suite))
        if missing:
            raise MatrixError(f"suite {suite.get('id', '<unknown>')} missing fields: {missing}")
        suite_id = suite["id"]
        if suite_id in seen:
            raise MatrixError(f"duplicate suite id: {suite_id}")
        seen.add(suite_id)
        if Path(suite["working_directory"]).is_absolute():
            raise MatrixError(f"{suite_id}: working_directory must be relative")
        if Path(suite["junit_output"]).is_absolute():
            raise MatrixError(f"{suite_id}: junit_output must be relative")
        if suite["runner"] not in {"pytest", "python_script"}:
            raise MatrixError(f"{suite_id}: unsupported runner {suite['runner']}")
        if not isinstance(suite["args"], list) or not all(isinstance(item, str) for item in suite["args"]):
            raise MatrixError(f"{suite_id}: args must be a list of strings")
    return matrix


def suite_selection(suites: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = []
    for suite in suites:
        if suite["requires_running_stack"] and not args.with_smoke:
            continue
        if args.fast and not suite["fast"]:
            continue
        if args.static_only and not suite.get("static", False):
            continue
        selected.append(suite)
    return selected


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def run_probe(cmd: list[str], cwd: Path, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        shell=False,
    )


def local_python_candidates(root: Path, explicit: str | None) -> list[str]:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    if os.getenv("TEST_PYTHON"):
        candidates.append(os.environ["TEST_PYTHON"])
    candidates.append(sys.executable)
    for exe in (PYTHON_CANDIDATES_WINDOWS if os.name == "nt" else PYTHON_CANDIDATES_POSIX):
        path = root / exe
        if path.exists():
            candidates.append(str(path))
    for name in ["python3", "python", "py"]:
        found = shutil.which(name)
        if found:
            candidates.append(found)
    deduped = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def validate_interpreter(root: Path, candidate: str) -> tuple[bool, str]:
    try:
        version = run_probe([candidate, "--version"], root)
    except Exception as exc:
        return False, f"{candidate}: version probe failed: {exc}"
    if version.returncode != 0:
        return False, f"{candidate}: version probe failed: {version.stderr.strip() or version.stdout.strip()}"
    try:
        pytest = run_probe([candidate, "-m", "pytest", "--version"], root)
    except Exception as exc:
        return False, f"{candidate}: pytest probe failed: {exc}"
    if pytest.returncode != 0:
        return False, f"{candidate}: pytest unavailable: {pytest.stderr.strip() or pytest.stdout.strip()}"
    probe_code = "import fastapi, httpx, pydantic, pytest, requests, yaml; print('imports-ok')"
    imports = run_probe([candidate, "-c", probe_code], root)
    if imports.returncode != 0:
        return False, f"{candidate}: missing test dependency: {imports.stderr.strip() or imports.stdout.strip()}"
    return True, f"{version.stdout.strip() or version.stderr.strip()}; {pytest.stdout.strip()}"


def choose_interpreter(root: Path, explicit: str | None) -> tuple[str | None, list[str]]:
    failures: list[str] = []
    for candidate in local_python_candidates(root, explicit):
        ok, detail = validate_interpreter(root, candidate)
        if ok:
            return candidate, [detail]
        failures.append(detail)
    return None, failures


def path_env(paths: list[str], root: Path) -> str:
    resolved = [str((root / item).resolve()) for item in paths]
    return os.pathsep.join(resolved)


def base_env(root: Path, suite: dict[str, Any], output_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["TEST_MATRIX_SUITE"] = suite["id"]
    env["TEST_RESULTS_DIR"] = str(output_dir)
    if suite.get("pythonpath"):
        env["PYTHONPATH"] = path_env(suite["pythonpath"], root)
    env.update({str(k): str(v) for k, v in suite.get("environment", {}).items()})
    if suite.get("forbidden_network"):
        env.update(OFFLINE_PROXY_ENV)
    return env


def junit_path(root: Path, output_dir: Path, suite: dict[str, Any], docker: bool = False) -> Path:
    default = Path(suite["junit_output"])
    if docker:
        return Path("/test-results") / "junit" / default.name
    return output_dir / "junit" / default.name


def local_command(python: str, suite: dict[str, Any], junit: Path) -> list[str]:
    if suite["runner"] == "pytest":
        return [python, "-m", "pytest", "-p", "no:cacheprovider", *suite["args"], "--junitxml", str(junit)]
    return [python, *suite["args"]]


def parse_junit(path: Path) -> dict[str, int]:
    counts = {"tests": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    if not path.exists():
        return counts
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return counts
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    for suite in suites:
        tests = int(float(suite.attrib.get("tests", "0")))
        failures = int(float(suite.attrib.get("failures", "0")))
        errors = int(float(suite.attrib.get("errors", "0")))
        skipped = int(float(suite.attrib.get("skipped", "0")))
        counts["tests"] += tests
        counts["failed"] += failures + errors
        counts["errors"] += errors
        counts["skipped"] += skipped
    counts["passed"] = max(0, counts["tests"] - counts["failed"] - counts["skipped"])
    return counts


def write_synthetic_junit(path: Path, suite_id: str, returncode: int, duration: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    testsuite = ET.Element(
        "testsuite",
        {
            "name": suite_id,
            "tests": "1",
            "failures": "0" if returncode == 0 else "1",
            "errors": "0",
            "skipped": "0",
            "time": f"{duration:.3f}",
        },
    )
    case = ET.SubElement(testsuite, "testcase", {"classname": suite_id, "name": suite_id, "time": f"{duration:.3f}"})
    if returncode != 0:
        failure = ET.SubElement(case, "failure", {"message": f"return code {returncode}"})
        failure.text = f"{suite_id} failed with return code {returncode}"
    ET.ElementTree(testsuite).write(path, encoding="utf-8", xml_declaration=True)


def run_subprocess(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    log_path: Path,
) -> tuple[int, float]:
    started = time.monotonic()
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except KeyboardInterrupt:
        process.terminate()
        raise
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
        output = (output or "") + f"\nTIMEOUT after {timeout} seconds\n"
        returncode = 124
    else:
        returncode = process.returncode
    duration = time.monotonic() - started
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output or "", encoding="utf-8")
    return returncode, duration


def docker_available(root: Path) -> tuple[bool, str]:
    if not command_exists("docker"):
        return False, "Docker CLI is unavailable"
    try:
        result = run_probe(["docker", "version", "--format", "{{.Client.Version}}"], root, timeout=20)
    except Exception as exc:
        return False, f"Docker probe failed: {exc}"
    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip()
    ps = run_probe(["docker", "ps", "--format", "{{.ID}}"], root, timeout=20)
    if ps.returncode != 0:
        return False, ps.stderr.strip() or ps.stdout.strip()
    return True, result.stdout.strip()


def ensure_test_image(root: Path, image: str) -> None:
    cmd = ["docker", "build", "-f", "Dockerfile.test", "-t", image, "."]
    result = run_probe(cmd, root, timeout=900)
    if result.returncode != 0:
        raise MatrixError(f"Docker test image build failed:\n{result.stdout}\n{result.stderr}")


def docker_command(root: Path, output_dir: Path, suite: dict[str, Any], image: str) -> list[str]:
    container_junit = PurePosixPath("/test-results") / "junit" / Path(suite["junit_output"]).name
    inner = local_command("python", suite, container_junit)
    workdir = "/repo" if suite["working_directory"] == "." else f"/repo/{suite['working_directory'].replace(os.sep, '/')}"
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none" if suite.get("forbidden_network") else "bridge",
        "-v",
        f"{root}:/repo:ro",
        "-v",
        f"{output_dir}:/test-results",
        "-w",
        workdir,
        "-e",
        "TEST_RESULTS_DIR=/test-results",
        "-e",
        f"TEST_MATRIX_SUITE={suite['id']}",
    ]
    for key, value in {**suite.get("environment", {}), **(OFFLINE_PROXY_ENV if suite.get("forbidden_network") else {})}.items():
        cmd.extend(["-e", f"{key}={value}"])
    if suite.get("pythonpath"):
        cmd.extend(["-e", "PYTHONPATH=" + os.pathsep.join(f"/repo/{p}" for p in suite["pythonpath"])])
    cmd.append(image)
    cmd.extend(inner)
    return cmd


def run_suite_local(root: Path, output_dir: Path, python: str, suite: dict[str, Any]) -> dict[str, Any]:
    suite_id = suite["id"]
    cwd = root / suite["working_directory"]
    junit = junit_path(root, output_dir, suite)
    log_path = output_dir / "logs" / f"{suite_id}.log"
    junit.parent.mkdir(parents=True, exist_ok=True)
    cmd = local_command(python, suite, junit)
    env = base_env(root, suite, output_dir)
    print(f"[RUN] {suite_id} local")
    rc, duration = run_subprocess(cmd, cwd, env, int(suite["timeout_seconds"]), log_path)
    if suite["runner"] != "pytest":
        write_synthetic_junit(junit, suite_id, rc, duration)
    counts = parse_junit(junit)
    status = "PASS" if rc == 0 else "FAIL"
    return {
        "id": suite_id,
        "status": status,
        "returncode": rc,
        "duration_seconds": round(duration, 3),
        "command": cmd,
        "working_directory": relpath(cwd, root),
        "log_path": relpath(log_path, root),
        "junit_path": relpath(junit, root),
        "network_policy": "blocked-by-invalid-proxy-env" if suite.get("forbidden_network") else "allowed-localhost-smoke",
        **counts,
    }


def run_suite_docker(root: Path, output_dir: Path, suite: dict[str, Any], image: str) -> dict[str, Any]:
    suite_id = suite["id"]
    host_junit = output_dir / "junit" / Path(suite["junit_output"]).name
    log_path = output_dir / "logs" / f"{suite_id}.log"
    host_junit.parent.mkdir(parents=True, exist_ok=True)
    cmd = docker_command(root, output_dir, suite, image)
    print(f"[RUN] {suite_id} docker")
    rc, duration = run_subprocess(cmd, root, os.environ.copy(), int(suite["timeout_seconds"]) + 30, log_path)
    if suite["runner"] != "pytest":
        write_synthetic_junit(host_junit, suite_id, rc, duration)
    counts = parse_junit(host_junit)
    status = "PASS" if rc == 0 else "FAIL"
    return {
        "id": suite_id,
        "status": status,
        "returncode": rc,
        "duration_seconds": round(duration, 3),
        "command": cmd,
        "working_directory": suite["working_directory"],
        "log_path": relpath(log_path, root),
        "junit_path": relpath(host_junit, root),
        "network_policy": "docker-network-none" if suite.get("forbidden_network") else "docker-bridge-for-smoke",
        "docker_image": image,
        **counts,
    }


def stack_is_running(root: Path) -> tuple[bool, str]:
    if not command_exists("docker"):
        return False, "Docker CLI is unavailable; smoke requires an already running Compose stack."
    cmd = ["docker", "compose", "--project-directory", str(root), "ps", "--format", "json"]
    result = run_probe(cmd, root, timeout=20)
    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip()
    if not result.stdout.strip():
        return False, "No Compose services were reported. Start the stack separately before --with-smoke."
    unhealthy = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        state = str(item.get("State", ""))
        health = str(item.get("Health", ""))
        name = item.get("Service") or item.get("Name")
        if state != "running" or (health and health != "healthy"):
            unhealthy.append(f"{name}: state={state} health={health}")
    if unhealthy:
        return False, "Compose stack is not healthy: " + "; ".join(unhealthy)
    return True, "Compose stack appears running and healthy."


def write_summaries(root: Path, output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        f"TelcoMind test matrix summary",
        f"start: {summary['start_time_utc']}",
        f"end: {summary['end_time_utc']}",
        f"duration_seconds: {summary['duration_seconds']}",
        f"execution_mode: {summary['execution_mode']}",
        f"interpreter: {summary.get('interpreter') or summary.get('docker_image') or 'unavailable'}",
        "",
        "Suites:",
    ]
    for suite in summary["suites"]:
        lines.append(
            f"- {suite['id']}: {suite['status']} tests={suite['tests']} passed={suite['passed']} "
            f"failed={suite['failed']} skipped={suite['skipped']} duration={suite['duration_seconds']}s "
            f"log={suite['log_path']} junit={suite['junit_path']}"
        )
    lines.extend(
        [
            "",
            f"overall_required_status: {summary['overall_required_status']}",
            "known_limitations:",
            "- Offline tests do not prove live Simu5G execution.",
            "- Offline tests do not prove full semantic RAG ingestion or model download behavior.",
            "- Optional smoke requires a separately started healthy root Compose stack.",
        ]
    )
    (output_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="Run only suites marked fast.")
    parser.add_argument("--static-only", action="store_true", help="Run only static/hygiene/integrity suites.")
    parser.add_argument("--with-smoke", action="store_true", help="Also run optional smoke against an already running stack.")
    parser.add_argument("--list", action="store_true", help="List suites and exit.")
    parser.add_argument("--output-dir", default="test-results", help="Directory for logs, JUnit, and summaries.")
    parser.add_argument("--python", dest="python_exe", help="Python interpreter to use in local mode.")
    parser.add_argument("--execution-mode", choices=["auto", "local", "docker"], default="auto")
    parser.add_argument("--docker-image", default="telcomind/test-runner:batch8")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = find_repo_root(Path(__file__).resolve())
    matrix = load_matrix(root)
    suites = suite_selection(matrix["suites"], args)
    if args.list:
        for suite in suites:
            required = "required" if suite["required"] else "optional"
            print(f"{suite['id']}\t{required}\t{suite['category']}\t{suite['description']}")
        return 0
    if args.with_smoke:
        healthy, detail = stack_is_running(root)
        if not healthy:
            print(f"[UNAVAILABLE] optional_smoke: {detail}")
            if args.execution_mode == "local":
                pass
        else:
            print(f"[SMOKE] {detail}")

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    (output_dir / "junit").mkdir(parents=True, exist_ok=True)

    start = utc_now()
    started = time.monotonic()
    selected_mode = args.execution_mode
    interpreter: str | None = None
    interpreter_details: list[str] = []
    docker_image: str | None = None

    if selected_mode in {"auto", "local"}:
        interpreter, interpreter_details = choose_interpreter(root, args.python_exe)
        if interpreter:
            selected_mode = "local"
        elif args.execution_mode == "local":
            print("[UNAVAILABLE] local Python dependencies are unavailable:")
            for failure in interpreter_details:
                print(f"  - {failure}")
            return 2

    if selected_mode in {"auto", "docker"}:
        ok, detail = docker_available(root)
        if not ok:
            print(f"[UNAVAILABLE] Docker fallback is unavailable: {detail}")
            if args.execution_mode == "docker":
                return 2
            print("[UNAVAILABLE] No local Python interpreter and no Docker fallback are available.")
            return 2
        docker_image = args.docker_image
        ensure_test_image(root, docker_image)
        selected_mode = "docker"

    results = []
    required_failure = False
    try:
        for suite in suites:
            if suite["requires_running_stack"]:
                healthy, detail = stack_is_running(root)
                if not healthy:
                    result = {
                        "id": suite["id"],
                        "status": "UNAVAILABLE",
                        "returncode": 2,
                        "duration_seconds": 0,
                        "command": [],
                        "working_directory": suite["working_directory"],
                        "log_path": "",
                        "junit_path": suite["junit_output"],
                        "network_policy": "requires-running-stack",
                        "tests": 0,
                        "passed": 0,
                        "failed": 0,
                        "skipped": 0,
                        "errors": 0,
                        "unavailable_reason": detail,
                    }
                elif selected_mode == "local" and interpreter:
                    result = run_suite_local(root, output_dir, interpreter, suite)
                else:
                    result = run_suite_docker(root, output_dir, suite, docker_image or args.docker_image)
            elif selected_mode == "local" and interpreter:
                result = run_suite_local(root, output_dir, interpreter, suite)
            else:
                result = run_suite_docker(root, output_dir, suite, docker_image or args.docker_image)
            results.append(result)
            if suite["required"] and result["status"] != "PASS":
                required_failure = True
            print(f"[{result['status']}] {suite['id']} ({result['duration_seconds']}s)")
    except KeyboardInterrupt:
        print("Interrupted; child process was terminated.")
        return 130

    duration = round(time.monotonic() - started, 3)
    summary = {
        "schema_version": 1,
        "start_time_utc": start,
        "end_time_utc": utc_now(),
        "duration_seconds": duration,
        "execution_mode": selected_mode,
        "platform": platform.platform(),
        "interpreter": interpreter,
        "interpreter_details": interpreter_details,
        "docker_image": docker_image,
        "offline_network_policy": "docker network none for docker suites; invalid proxy environment for local required suites",
        "suites": results,
        "overall_required_status": "FAIL" if required_failure else "PASS",
    }
    write_summaries(root, output_dir, summary)
    print(f"Summary: {relpath(output_dir / 'summary.txt', root)}")
    return 1 if required_failure else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MatrixError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(2)
