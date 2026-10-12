import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def _tracked_files() -> list[Path]:
    tracked = subprocess.run(
        ["git", "-c", f"core.excludesfile={os.devnull}", "-c", "core.quotePath=false", "ls-files", "-z"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        check=True,
    )
    untracked = subprocess.run(
        ["git", "-c", f"core.excludesfile={os.devnull}", "-c", "core.quotePath=false", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        check=True,
    )
    tracked_names = tracked.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    untracked_names = untracked.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    files = [line for line in [*tracked_names, *untracked_names] if line.strip()]
    return [ROOT / line for line in files]


def test_json_and_jsonl_files_parse():
    for path in _tracked_files():
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        if path.suffix == ".jsonl":
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if line.strip():
                    json.loads(line)


def test_yaml_files_parse():
    class ComposeLoader(yaml.SafeLoader):
        pass
    ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node, deep=True))
    for path in _tracked_files():
        if path.suffix.lower() in {".yml", ".yaml"}:
            loader = ComposeLoader if path.name.startswith("docker-compose.") else yaml.SafeLoader
            docs = list(yaml.load_all(path.read_text(encoding="utf-8"), Loader=loader))
            assert docs or path.stat().st_size == 0


def test_compose_files_render_when_docker_compose_is_available():
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI unavailable; structured YAML parsing covers this platform.")
    for compose in [ROOT / "docker-compose.yml", ROOT / "docker-compose.test.yml"]:
        if not compose.exists():
            continue
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose), "config"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0 and "permission denied" in (result.stderr + result.stdout).lower():
            pytest.skip("Docker daemon/config is unavailable to this user.")
        assert result.returncode == 0, result.stderr + result.stdout


def test_shell_and_powershell_scripts_parse_where_tools_exist():
    if shutil.which("bash"):
        for script in ["deploy.sh", "test.sh"]:
            result = subprocess.run(["bash", "-n", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert result.returncode == 0, result.stderr
    else:
        pytest.skip("bash unavailable on this platform.")

    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell:
        for script in ["deploy.ps1", "test.ps1"]:
            result = subprocess.run(
                [powershell, "-NoProfile", "-Command", f"$null = [scriptblock]::Create((Get-Content -Raw -LiteralPath '{script}'))"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert result.returncode == 0, result.stderr


def test_python_files_compile_without_running_component_imports():
    for path in _tracked_files():
        if path.suffix == ".py" and ".venv" not in path.parts:
            ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))


def test_no_active_tailscale_or_secret_defaults_in_tracked_text():
    tailscale = re.compile(r"https?://100\.\d{1,3}\.\d{1,3}\.\d{1,3}|Tailscale", re.IGNORECASE)
    secret = re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([A-Za-z0-9_./+-]{16,})")
    active_network_files = {
        ".env.example",
        "docker-compose.yml",
        "CODE/.env.example",
        "CODE/Agent/tools/tools.py",
        "CODE/Agent/agent.py",
        "CODE/Agent/gateway.py",
        "CODE/Agent/ui/app.py",
        "CODE/Agent/docker-compose.yml",
        "CODE/RAG/docker-compose.yml",
        "CODE/Simulation/docker-compose.yml",
    }
    allowed_secret_paths = {
        "CODE/Agent/k8s/secret.yaml",
    }
    for path in _tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in {".pdf", ".png", ".vci", ".sca"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if rel in allowed_secret_paths:
            continue
        if rel in active_network_files:
            assert tailscale.search(text) is None, rel
        for match in secret.finditer(text):
            value = match.group(2)
            if value.startswith(("config.", "os.getenv", "getenv", "env.")):
                continue
            assert False, rel


def test_ports_contracts_and_profiles_remain_safe():
    services = json.loads((ROOT / "contracts" / "services.json").read_text(encoding="utf-8"))["services"]
    ports = [service["host_port"] for service in services]
    assert len(ports) == len(set(ports))

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "test-runner" not in compose["services"]
    assert compose["services"]["vllm"]["profiles"] == ["gpu-llm"]
    assert compose["services"]["rag"]["environment"]["RAG_PROFILE"] == "${RAG_PROFILE:-quickstart}"
    assert compose["services"]["rag"]["environment"]["RAG_SYNTHESIS_BACKEND"] == "${RAG_SYNTHESIS_BACKEND:-deterministic}"
    assert compose["services"]["rag"]["environment"]["LLM_REQUIRED"] == "${LLM_REQUIRED:-false}"
