#!/usr/bin/env python3
"""Read-only repository hygiene checks for submission readiness batches."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import stat
import subprocess
import sys
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - reported as a hygiene failure when needed.
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
SIM_RESULTS = Path("CODE/Simulation/app/scenarios/results")
SIM_GENERATED = Path("CODE/Simulation/app/scenarios/generated")
SIM_FIXTURES = Path("CODE/Simulation/fixtures/replay")
SIM_FIXTURE_MANIFEST = SIM_FIXTURES / "phase_bootstrap_normal" / "manifest.json"
ALLOWED_RUNTIME_TRACKED = {"README.md", ".gitkeep"}
RAG_CHROMA = Path("CODE/RAG/storage/chroma")
RAG_QUICKSTART_DIR = Path("CODE/RAG/quickstart")
RAG_QUICKSTART_CORPUS = RAG_QUICKSTART_DIR / "corpus.jsonl"
RAG_QUICKSTART_MANIFEST = RAG_QUICKSTART_DIR / "manifest.json"
RAG_QUICKSTART_MAX_BYTES = 2 * 1024 * 1024
RAG_STORAGE_CANDIDATES = [
    Path("CODE/RAG/storage"),
    RAG_CHROMA,
    Path("CODE/RAG/storage/faiss"),
    Path("CODE/RAG/storage/qdrant"),
    Path("CODE/RAG/storage/weaviate"),
]
REQUIRED_ROOT_FILES = [
    "README.md",
    "LICENSE",
    "TECHNICAL_REPORT.pdf",
    "docker-compose.yml",
    "deploy.sh",
    "deploy.ps1",
    ".dockerignore",
]
SERVICE_CONTRACT = Path("contracts/services.json")
SIMULATION_DEFAULT_EXAMPLES = [
    Path(".env.example"),
    Path("CODE/.env.example"),
    Path("CODE/Simulation/docker-compose.yml"),
]
ACTIVE_NETWORK_CONFIG_FILES = [
    Path(".env.example"),
    Path("docker-compose.yml"),
    Path("CODE/.env.example"),
    Path("CODE/Agent/tools/tools.py"),
    Path("CODE/Agent/agent.py"),
    Path("CODE/Agent/gateway.py"),
    Path("CODE/Agent/ui/app.py"),
    Path("CODE/Agent/docker-compose.yml"),
    Path("CODE/RAG/docker-compose.yml"),
    Path("CODE/Simulation/docker-compose.yml"),
]
SYNTHESIS_DEFAULT_FILES = [
    Path(".env.example"),
    Path("docker-compose.yml"),
    Path("CODE/.env.example"),
    Path("CODE/RAG/.env.example"),
    Path("CODE/RAG/docker-compose.yml"),
]
FORBIDDEN_ACTIVE_NETWORK_PATTERNS = [
    re.compile(r"Tailscale", re.IGNORECASE),
    re.compile(r"https?://100\.\d{1,3}\.\d{1,3}\.\d{1,3}"),
]
ROOT_COMPOSE = Path("docker-compose.yml")
ROOT_DEPLOY_SH = Path("deploy.sh")
ROOT_DEPLOY_PS1 = Path("deploy.ps1")
ROOT_TEST_SH = Path("test.sh")
ROOT_TEST_PS1 = Path("test.ps1")
ROOT_DOCKERIGNORE = Path(".dockerignore")
ROOT_SMOKE_TEST = Path("scripts/smoke_test.py")
ROOT_TEST_RUNNER = Path("scripts/run_test_matrix.py")
ROOT_TEST_MATRIX = Path("tests/test_matrix.json")
ROOT_TEST_DOC = Path("DOCs/TESTING.md")
ROOT_DOCKERFILE_TEST = Path("Dockerfile.test")
ROOT_COMPOSE_TEST = Path("docker-compose.test.yml")
ROOT_REQUIREMENTS_TEST = Path("requirements.test.txt")
ROOT_TEST_RESULTS = Path("test-results")
ROOT_E2E_RESULTS = Path("e2e-results")
DEMO_SCENARIOS_JSON = Path("demo/quickstart_scenarios.json")
DEMO_RUNNER_SCRIPT = Path("scripts/run_demo_scenarios.py")
DEMO_SCENARIOS_DOC = Path("DOCs/DEMO_SCENARIOS.md")
CREDENTIAL_BEARING_URL = re.compile(r"https?://[^/\s:@]+:[^@\s/]+@")
ABS_LOCAL_PATH_PATTERN = re.compile(r"[A-Za-z]:\\|/Users/|/home/")
TRACKED_CACHE_PATTERNS = [
    "*/__pycache__/*",
    "__pycache__/*",
    "*.pyc",
    "*.pyo",
    "CODE/RAG/storage/chroma/*",
    "CODE/RAG/storage/chroma/**/*",
    "*/huggingface/*",
    "*/huggingface/**/*",
    "*/model_cache/*",
    "*/model_cache/**/*",
    "*/torch_cache/*",
    "*/torch_cache/**/*",
]
SECRET_ENV_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.test",
    ".envrc",
}
ALLOWED_ENV_NAMES = {
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.defaults",
}
FORBIDDEN_TRACKED_NAME_PARTS = [
    "credential",
    "credentials",
    "api_key",
    "apikey",
    "access_token",
]
GENERAL_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "huggingface",
    "hf_cache",
    "model_cache",
    "torch_cache",
    ".torch",
}
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


@dataclass
class WalkResult:
    files: int = 0
    size: int = 0
    skipped_dirs: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    excluded_dirs: list[str] = field(default_factory=list)


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_worktree_path(git_path: str) -> Path:
    direct = ROOT / git_path
    if direct.exists():
        return direct

    current = ROOT
    for part in Path(git_path).parts:
        candidate = current / part
        if candidate.exists():
            current = candidate
            continue
        try:
            matches = [child for child in current.iterdir() if child.name == part]
        except (FileNotFoundError, OSError, PermissionError):
            return direct
        if not matches:
            return direct
        current = matches[0]
    return current


def run_git(args: list[str], counts: dict[str, int] | None = None) -> list[str]:
    cmd = ["git", "-c", f"core.excludesfile={os.devnull}", "-c", "core.quotePath=false", *args]
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        if counts is not None:
            emit("FAIL", f"git {' '.join(args)} could not run: {exc}", counts)
        else:
            print(f"FAIL git {' '.join(args)} could not run: {exc}")
        return []
    return [line for line in result.stdout.splitlines() if line]


def fmt_size(num_bytes: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{num_bytes} B"


def is_reparse_point(entry: os.DirEntry[str]) -> bool:
    try:
        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except (FileNotFoundError, OSError, PermissionError):
        return False
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)


def safe_walk(path: Path, *, skip_general: bool) -> WalkResult:
    result = WalkResult()
    seen: set[tuple[int, int]] = set()

    def visit(directory: Path) -> None:
        try:
            directory_stat = directory.stat()
        except (FileNotFoundError, OSError, PermissionError):
            result.skipped_dirs.append(rel(directory))
            return
        identity = (getattr(directory_stat, "st_dev", 0), getattr(directory_stat, "st_ino", 0))
        if identity in seen:
            result.skipped_dirs.append(f"{rel(directory)} (already visited)")
            return
        seen.add(identity)

        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    entry_path = Path(entry.path)
                    entry_rel = rel(entry_path)
                    try:
                        if entry.is_symlink() or is_reparse_point(entry):
                            result.skipped_dirs.append(entry_rel)
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if skip_general and entry.name in GENERAL_SKIP_DIRS:
                                result.excluded_dirs.append(entry_rel)
                                continue
                            visit(entry_path)
                        elif entry.is_file(follow_symlinks=False):
                            try:
                                file_stat = entry.stat(follow_symlinks=False)
                            except (FileNotFoundError, OSError, PermissionError):
                                result.skipped_files.append(entry_rel)
                                continue
                            result.files += 1
                            result.size += file_stat.st_size
                    except (FileNotFoundError, OSError, PermissionError):
                        result.skipped_dirs.append(entry_rel)
        except (FileNotFoundError, OSError, PermissionError):
            result.skipped_dirs.append(rel(directory))

    if path.exists():
        visit(path)
    return result


def tracked_under(tracked: list[str], directory: Path) -> list[str]:
    prefix = directory.as_posix().rstrip("/") + "/"
    return [item for item in tracked if item.startswith(prefix)]


def tracked_measure(paths: list[str]) -> tuple[int, int, list[str]]:
    total_size = 0
    file_count = 0
    missing: list[str] = []
    for item in paths:
        path = resolve_worktree_path(item)
        try:
            file_stat = path.stat()
        except FileNotFoundError:
            missing.append(item)
            continue
        except (OSError, PermissionError):
            missing.append(f"{item} (inaccessible)")
            continue
        if stat.S_ISREG(file_stat.st_mode):
            file_count += 1
            total_size += file_stat.st_size
    return file_count, total_size, missing


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def env_like_violation(path: str) -> bool:
    name = Path(path).name.lower()
    if name in ALLOWED_ENV_NAMES:
        return False
    if name in SECRET_ENV_NAMES:
        return True
    return name.startswith(".env.") and name not in ALLOWED_ENV_NAMES


def emit(level: str, message: str, counts: dict[str, int]) -> None:
    counts[level] += 1
    print(f"{level} {message}")


def print_limited(label: str, items: list[str], limit: int = 20) -> None:
    if not items:
        return
    print(f"  {label}:")
    for item in items[:limit]:
        print(f"  - {item}")
    if len(items) > limit:
        print(f"  - ... {len(items) - limit} more")


def main() -> int:
    os.chdir(ROOT)
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    tracked = run_git(["ls-files"], counts)
    untracked = run_git(["ls-files", "--others", "--exclude-standard"], counts)
    versioned_candidates = set(tracked) | set(untracked)

    local = safe_walk(ROOT, skip_general=True)
    emit(
        "PASS",
        f"local working directory accessible content: {local.files} files, {fmt_size(local.size)}",
        counts,
    )
    if local.excluded_dirs:
        emit(
            "WARN",
            f"excluded dependency/cache directories during local size walk: {len(local.excluded_dirs)}",
            counts,
        )
        print_limited("excluded paths", local.excluded_dirs)
    if local.skipped_dirs or local.skipped_files:
        emit(
            "WARN",
            f"skipped junction/reparse/inaccessible paths: {len(local.skipped_dirs) + len(local.skipped_files)}",
            counts,
        )
        print_limited("skipped paths", local.skipped_dirs + local.skipped_files)
    else:
        emit("PASS", "no junction/reparse/inaccessible paths were entered or skipped", counts)

    tracked_file_count, tracked_size, missing_tracked = tracked_measure(tracked)
    emit(
        "PASS",
        f"Git-tracked submission content currently accessible: {tracked_file_count} files, {fmt_size(tracked_size)}",
        counts,
    )
    if missing_tracked:
        emit("WARN", f"tracked files missing from working tree, usually pending deletions: {len(missing_tracked)}", counts)
        print_limited("missing tracked paths", missing_tracked)

    tracked_cache = [
        path
        for path in tracked
        if matches_any(path, TRACKED_CACHE_PATTERNS) and resolve_worktree_path(path).exists()
    ]
    if tracked_cache:
        emit("FAIL", f"tracked Python bytecode/cache files remain in working tree: {len(tracked_cache)}", counts)
        print_limited("tracked cache paths", tracked_cache)
    else:
        emit("PASS", "no tracked Python bytecode/cache files remain in working tree", counts)

    untracked_cache = [path for path in untracked if matches_any(path, TRACKED_CACHE_PATTERNS)]
    if untracked_cache:
        emit("WARN", f"untracked non-ignored Python cache files are present: {len(untracked_cache)}", counts)
        print_limited("untracked cache paths", untracked_cache)
    else:
        emit("PASS", "no untracked non-ignored Python cache files reported by git", counts)

    env_violations = sorted({path for path in [*tracked, *untracked] if env_like_violation(path)})
    if env_violations:
        emit("FAIL", f"accidental tracked/untracked non-ignored .env files found: {len(env_violations)}", counts)
        print_limited("env paths", env_violations)
    else:
        emit("PASS", "no tracked or untracked non-ignored .env files found; examples/templates are allowed", counts)

    tracked_sensitive = []
    for path in tracked:
        if not resolve_worktree_path(path).exists():
            continue
        name = Path(path).name.lower()
        if any(part in name for part in FORBIDDEN_TRACKED_NAME_PARTS):
            tracked_sensitive.append(path)
    if tracked_sensitive:
        emit("FAIL", f"obvious credential/token-like files are tracked: {len(tracked_sensitive)}", counts)
        print_limited("tracked sensitive paths", sorted(set(tracked_sensitive)))
    else:
        emit("PASS", "no obvious credential/token-like tracked files found", counts)

    for label, rel_path in [("Simulation results", SIM_RESULTS), ("Simulation generated", SIM_GENERATED)]:
        local_runtime = safe_walk(ROOT / rel_path, skip_general=False)
        tracked_paths = tracked_under(tracked, rel_path)
        tracked_count, tracked_size, _ = tracked_measure(tracked_paths)
        unexpected_tracked = [
            path
            for path in tracked_paths
            if Path(path).name not in ALLOWED_RUNTIME_TRACKED
        ]
        if (ROOT / rel_path).exists():
            emit(
                "PASS",
                (
                    f"{label}: local {local_runtime.files} files, {fmt_size(local_runtime.size)}; "
                    f"tracked {tracked_count} files, {fmt_size(tracked_size)}"
                ),
                counts,
            )
            if unexpected_tracked:
                emit("FAIL", f"{label}: unexpected tracked runtime files remain: {len(unexpected_tracked)}", counts)
                print_limited("unexpected tracked runtime paths", unexpected_tracked)
            else:
                emit("PASS", f"{label}: tracked files are limited to README.md and .gitkeep", counts)
        else:
            emit("WARN", f"{label}: directory is absent", counts)

    fixture_paths = tracked_under(tracked, SIM_FIXTURES)
    fixture_count, fixture_size, missing_fixture = tracked_measure(fixture_paths)
    if (ROOT / SIM_FIXTURES).exists():
        emit("PASS", f"Simulation replay fixtures: tracked {fixture_count} files, {fmt_size(fixture_size)}", counts)
    else:
        emit("FAIL", f"Simulation replay fixture directory is absent: {SIM_FIXTURES.as_posix()}", counts)
    if missing_fixture:
        emit("FAIL", f"tracked fixture files are missing or inaccessible: {len(missing_fixture)}", counts)
        print_limited("missing fixture paths", missing_fixture)

    manifest_path = ROOT / SIM_FIXTURE_MANIFEST
    if not manifest_path.exists():
        emit("FAIL", f"Simulation fixture manifest is absent: {SIM_FIXTURE_MANIFEST.as_posix()}", counts)
    elif SIM_FIXTURE_MANIFEST.as_posix() not in tracked:
        emit("FAIL", f"Simulation fixture manifest is not tracked: {SIM_FIXTURE_MANIFEST.as_posix()}", counts)
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            emit("FAIL", f"Simulation fixture manifest cannot be loaded: {exc}", counts)
        else:
            emit("PASS", f"Simulation fixture manifest exists: {SIM_FIXTURE_MANIFEST.as_posix()}", counts)
            fixture_dir = manifest_path.parent
            manifest_failures = []
            for entry in manifest.get("files", []):
                filename = entry.get("filename")
                if not filename:
                    manifest_failures.append("manifest entry without filename")
                    continue
                file_path = fixture_dir / filename
                rel_file = rel(file_path)
                if rel_file not in tracked:
                    manifest_failures.append(f"{rel_file} is not tracked")
                    continue
                if not file_path.exists():
                    manifest_failures.append(f"{rel_file} is missing")
                    continue
                if file_path.stat().st_size != entry.get("size_bytes"):
                    manifest_failures.append(f"{rel_file} size mismatch")
                if file_sha256(file_path) != entry.get("sha256"):
                    manifest_failures.append(f"{rel_file} sha256 mismatch")
                source_path = entry.get("source_original_path", "")
                if not (
                    source_path.startswith(SIM_RESULTS.as_posix() + "/")
                    or source_path.startswith(SIM_GENERATED.as_posix() + "/")
                ):
                    manifest_failures.append(f"{rel_file} source path is not a Simulation runtime artifact")
            if manifest.get("live_simulation") is not False:
                manifest_failures.append("manifest must set live_simulation to false")
            if manifest.get("created_from_existing_repository_artifact") is not True:
                manifest_failures.append("manifest must mark fixture as created from existing repository artifacts")
            if manifest_failures:
                emit("FAIL", f"Simulation fixture manifest validation failures: {len(manifest_failures)}", counts)
                print_limited("fixture manifest failures", manifest_failures)
            else:
                emit("PASS", "Simulation fixture manifest files exist, are tracked, and match SHA-256 checksums", counts)

    if (ROOT / RAG_CHROMA).exists():
        chroma = safe_walk(ROOT / RAG_CHROMA, skip_general=False)
        emit("WARN", f"RAG Chroma runtime storage: {chroma.files} files, {fmt_size(chroma.size)}", counts)
    else:
        emit("WARN", "RAG Chroma runtime storage is absent", counts)

    for rel_path in RAG_STORAGE_CANDIDATES:
        path = ROOT / rel_path
        if path.exists():
            data = safe_walk(path, skip_general=False)
            emit("WARN", f"RAG runtime storage present at {rel_path.as_posix()}: {data.files} files, {fmt_size(data.size)}", counts)
        else:
            emit("PASS", f"RAG runtime storage absent at {rel_path.as_posix()}", counts)

    quickstart_failures = []
    corpus_path = ROOT / RAG_QUICKSTART_CORPUS
    manifest_path = ROOT / RAG_QUICKSTART_MANIFEST
    if not corpus_path.exists():
        quickstart_failures.append(f"missing {RAG_QUICKSTART_CORPUS.as_posix()}")
    if not manifest_path.exists():
        quickstart_failures.append(f"missing {RAG_QUICKSTART_MANIFEST.as_posix()}")
    quickstart_untracked = []
    if RAG_QUICKSTART_CORPUS.as_posix() not in versioned_candidates:
        quickstart_failures.append("quickstart corpus is not tracked or reported as an untracked commit candidate")
    elif RAG_QUICKSTART_CORPUS.as_posix() not in tracked:
        quickstart_untracked.append(RAG_QUICKSTART_CORPUS.as_posix())
    if RAG_QUICKSTART_MANIFEST.as_posix() not in versioned_candidates:
        quickstart_failures.append("quickstart manifest is not tracked or reported as an untracked commit candidate")
    elif RAG_QUICKSTART_MANIFEST.as_posix() not in tracked:
        quickstart_untracked.append(RAG_QUICKSTART_MANIFEST.as_posix())
    if corpus_path.exists() and corpus_path.stat().st_size > RAG_QUICKSTART_MAX_BYTES:
        quickstart_failures.append(
            f"quickstart corpus exceeds {fmt_size(RAG_QUICKSTART_MAX_BYTES)}: {fmt_size(corpus_path.stat().st_size)}"
        )
    if corpus_path.exists() and manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries = [
                json.loads(line)
                for line in corpus_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError) as exc:
            quickstart_failures.append(f"quickstart corpus/manifest cannot be parsed: {exc}")
        else:
            if manifest.get("chunk_count") != len(entries):
                quickstart_failures.append("quickstart manifest chunk_count mismatch")
            if manifest.get("corpus_sha256") != hashlib.sha256(corpus_path.read_bytes()).hexdigest():
                quickstart_failures.append("quickstart corpus sha256 mismatch")
            sources = {source.get("source"): source for source in manifest.get("sources", [])}
            if not sources:
                quickstart_failures.append("quickstart manifest has no sources")
            for source_rel, source in sources.items():
                if not isinstance(source_rel, str) or Path(source_rel).is_absolute() or ".." in Path(source_rel).parts:
                    quickstart_failures.append(f"quickstart source path is not portable: {source_rel}")
                    continue
                source_path = ROOT / "CODE/RAG" / source_rel
                if not source_path.exists():
                    quickstart_failures.append(f"quickstart source missing: {source_rel}")
                    continue
                if source_path.stat().st_size != source.get("size_bytes"):
                    quickstart_failures.append(f"quickstart source size mismatch: {source_rel}")
                if file_sha256(source_path) != source.get("sha256"):
                    quickstart_failures.append(f"quickstart source sha256 mismatch: {source_rel}")
            for entry in entries:
                metadata = entry.get("metadata", {})
                source_rel = metadata.get("source", "")
                if Path(str(source_rel)).is_absolute() or ".." in Path(str(source_rel)).parts:
                    quickstart_failures.append(f"quickstart chunk uses nonportable source: {entry.get('id')}")
                if entry.get("source_sha256") != sources.get(source_rel, {}).get("sha256"):
                    quickstart_failures.append(f"quickstart chunk source hash mismatch: {entry.get('id')}")
                text = entry.get("text", "")
                if hashlib.sha256(str(text).encode("utf-8")).hexdigest() != entry.get("text_sha256"):
                    quickstart_failures.append(f"quickstart chunk text hash mismatch: {entry.get('id')}")
    if quickstart_failures:
        emit("FAIL", f"RAG quickstart corpus validation failures: {len(quickstart_failures)}", counts)
        print_limited("quickstart corpus failures", quickstart_failures)
    else:
        emit(
            "PASS",
            f"RAG quickstart corpus and manifest validate under {fmt_size(RAG_QUICKSTART_MAX_BYTES)}",
            counts,
        )
    if quickstart_untracked:
        emit("WARN", "RAG quickstart corpus files are valid but not committed yet", counts)
        print_limited("untracked quickstart paths", quickstart_untracked)

    rag_default_findings = []
    for rel_path in [Path(".env.example"), Path("CODE/.env.example"), Path("CODE/RAG/.env.example"), Path("CODE/RAG/docker-compose.yml")]:
        path = ROOT / rel_path
        if not path.exists():
            rag_default_findings.append(f"{rel_path.as_posix()}: missing")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "RAG_PROFILE=quickstart" not in text and "RAG_PROFILE:-quickstart" not in text:
            rag_default_findings.append(f"{rel_path.as_posix()}: RAG_PROFILE quickstart default missing")
        if "RAG_AUTO_INGEST=false" not in text and "RAG_AUTO_INGEST:-false" not in text:
            rag_default_findings.append(f"{rel_path.as_posix()}: RAG_AUTO_INGEST=false default missing")
    if rag_default_findings:
        emit("FAIL", f"RAG quickstart defaults are not consistently documented: {len(rag_default_findings)}", counts)
        print_limited("RAG default findings", rag_default_findings)
    else:
        emit("PASS", "RAG examples and compose default to quickstart with auto-ingest disabled", counts)

    synthesis_findings = []
    credential_url_findings = []
    for rel_path in SYNTHESIS_DEFAULT_FILES:
        path = ROOT / rel_path
        if not path.exists():
            synthesis_findings.append(f"{rel_path.as_posix()}: missing")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "RAG_SYNTHESIS_BACKEND=deterministic" not in text and "RAG_SYNTHESIS_BACKEND:-deterministic" not in text:
            synthesis_findings.append(f"{rel_path.as_posix()}: deterministic synthesis default missing")
        if "LLM_REQUIRED=false" not in text and "LLM_REQUIRED:-false" not in text:
            synthesis_findings.append(f"{rel_path.as_posix()}: LLM_REQUIRED=false default missing")
        active_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if any(
            line.startswith("LLM_BASE_URL=http")
            or line.startswith("VLLM_BASE_URL=http")
            or "LLM_BASE_URL:-http" in line
            or "VLLM_BASE_URL:-http" in line
            for line in active_lines
        ):
            synthesis_findings.append(f"{rel_path.as_posix()}: LLM/vLLM URL is non-empty in default examples")
        if CREDENTIAL_BEARING_URL.search(text):
            credential_url_findings.append(rel_path.as_posix())
    if synthesis_findings:
        emit("FAIL", f"RAG synthesis defaults are not CPU-safe deterministic: {len(synthesis_findings)}", counts)
        print_limited("synthesis default findings", synthesis_findings)
    else:
        emit("PASS", "RAG synthesis examples and compose default to CPU-safe deterministic mode", counts)
    if credential_url_findings:
        emit("FAIL", f"credential-bearing URLs appear in synthesis examples: {len(credential_url_findings)}", counts)
        print_limited("credential-bearing URL paths", credential_url_findings)
    else:
        emit("PASS", "synthesis examples contain no credential-bearing URLs", counts)

    try:
        services = json.loads((ROOT / SERVICE_CONTRACT).read_text(encoding="utf-8")).get("services", [])
    except (OSError, json.JSONDecodeError):
        services = []
    port_by_name = {service.get("name"): service.get("host_port") for service in services}
    if port_by_name.get("gateway") == 8888 and port_by_name.get("vllm") == 8080:
        emit("PASS", "Gateway and optional vLLM ports remain distinct", counts)
    else:
        emit("FAIL", f"Gateway/vLLM port contract is unexpected: {port_by_name}", counts)

    vllm_latest_findings = []
    for rel_path in [Path("CODE/RAG/docker-compose.yml"), Path("DOCs/LLM_BACKENDS.md"), Path("CODE/RAG/README.md")]:
        path = ROOT / rel_path
        if path.exists() and re.search(r"vllm[^:\n]*:latest", path.read_text(encoding="utf-8", errors="replace"), re.IGNORECASE):
            vllm_latest_findings.append(rel_path.as_posix())
    if vllm_latest_findings:
        emit("FAIL", f"optional vLLM references use a latest tag: {len(vllm_latest_findings)}", counts)
        print_limited("vLLM latest references", vllm_latest_findings)
    else:
        emit("PASS", "optional vLLM references do not introduce a latest image tag", counts)

    for filename in REQUIRED_ROOT_FILES:
        path = ROOT / filename
        if path.exists():
            emit("PASS", f"required root file present: {filename}", counts)
        else:
            emit("WARN", f"future submission deliverable missing at root: {filename}", counts)

    root_deployment_findings = []
    root_compose_path = ROOT / ROOT_COMPOSE
    root_compose = None
    if not root_compose_path.exists():
        root_deployment_findings.append("root docker-compose.yml is missing")
    elif yaml is None:
        try:
            result = subprocess.run(
                ["docker", "compose", "--project-directory", str(ROOT), "config", "--format", "json"],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            root_compose = json.loads(result.stdout)
        except Exception as exc:
            root_deployment_findings.append(
                f"PyYAML is unavailable and docker compose config could not parse root docker-compose.yml: {exc}"
            )
    else:
        try:
            root_compose = yaml.safe_load(root_compose_path.read_text(encoding="utf-8"))
        except Exception as exc:
            root_deployment_findings.append(f"root docker-compose.yml cannot be parsed: {exc}")

    if root_compose:
        services = root_compose.get("services", {})
        required_services = {"simulation", "rag", "agent", "gateway", "ui"}
        missing_services = sorted(required_services - set(services))
        if missing_services:
            root_deployment_findings.append(f"missing required root services: {missing_services}")
        compose_source_text = root_compose_path.read_text(encoding="utf-8", errors="replace")
        vllm = services.get("vllm")
        if vllm is not None and vllm.get("profiles") != ["gpu-llm"]:
            root_deployment_findings.append("vllm is not isolated behind the gpu-llm profile")
        if vllm is None and "gpu-llm" not in compose_source_text:
            root_deployment_findings.append("vllm optional gpu-llm profile is not visible in root compose source")
        for service_name in required_services:
            service = services.get(service_name, {})
            if "healthcheck" not in service:
                root_deployment_findings.append(f"{service_name} lacks a healthcheck")
            if "profiles" in service:
                root_deployment_findings.append(f"{service_name} is incorrectly profile-gated")
            if service.get("privileged") is True:
                root_deployment_findings.append(f"{service_name} uses privileged mode")
            if service.get("network_mode") == "host":
                root_deployment_findings.append(f"{service_name} uses host networking")
            if "deploy" in service and re.search(r"gpu|nvidia", json.dumps(service.get("deploy"), sort_keys=True), re.IGNORECASE):
                root_deployment_findings.append(f"{service_name} has a GPU reservation")
            for volume in service.get("volumes", []):
                volume_text = str(volume)
                source = volume_text.split(":", 1)[0]
                if "/var/run/docker.sock" in volume_text:
                    root_deployment_findings.append(f"{service_name} mounts the Docker socket")
                if Path(source).is_absolute():
                    root_deployment_findings.append(f"{service_name} uses an absolute bind mount: {source}")
        compose_text = root_compose_path.read_text(encoding="utf-8", errors="replace")
        required_fragments = [
            "SIMULATION_DEFAULT_MODE: ${SIMULATION_DEFAULT_MODE:-replay}",
            "SIMULATION_LIVE_ENABLED: ${SIMULATION_LIVE_ENABLED:-false}",
            "RAG_PROFILE: ${RAG_PROFILE:-quickstart}",
            "RAG_AUTO_INGEST: ${RAG_AUTO_INGEST:-false}",
            "RAG_SYNTHESIS_BACKEND: ${RAG_SYNTHESIS_BACKEND:-deterministic}",
            "LLM_REQUIRED: ${LLM_REQUIRED:-false}",
            "http://simulation:7000",
            "http://rag:7001",
            "http://agent:9090",
            "HOST_SIMULATION_PORT",
            "HOST_RAG_PORT",
            "HOST_GATEWAY_PORT",
            "HOST_AGENT_PORT",
            "HOST_UI_PORT",
        ]
        for fragment in required_fragments:
            if fragment not in compose_text:
                root_deployment_findings.append(f"root compose missing expected fragment: {fragment}")
        if "host.docker.internal" in compose_text:
            root_deployment_findings.append("root compose uses host.docker.internal")
        if re.search(r"LLM_API_KEY:\s+[^$\n]+", compose_text):
            root_deployment_findings.append("root compose appears to contain a literal LLM_API_KEY value")

    for rel_path in [ROOT_DEPLOY_SH, ROOT_DEPLOY_PS1, ROOT_DOCKERIGNORE, ROOT_SMOKE_TEST]:
        if not (ROOT / rel_path).exists():
            root_deployment_findings.append(f"{rel_path.as_posix()} is missing")
    for rel_path in [
        ROOT_TEST_SH,
        ROOT_TEST_PS1,
        ROOT_TEST_RUNNER,
        ROOT_TEST_MATRIX,
        ROOT_TEST_DOC,
        ROOT_DOCKERFILE_TEST,
        ROOT_COMPOSE_TEST,
        ROOT_REQUIREMENTS_TEST,
    ]:
        if not (ROOT / rel_path).exists():
            root_deployment_findings.append(f"Batch 8 test artifact is missing: {rel_path.as_posix()}")
    deploy_sh_path = ROOT / ROOT_DEPLOY_SH
    if deploy_sh_path.exists() and b"\r\n" in deploy_sh_path.read_bytes():
        root_deployment_findings.append("deploy.sh has CRLF line endings")
    test_sh_path = ROOT / ROOT_TEST_SH
    if test_sh_path.exists() and b"\r\n" in test_sh_path.read_bytes():
        root_deployment_findings.append("test.sh has CRLF line endings")
    dockerignore_path = ROOT / ROOT_DOCKERIGNORE
    if dockerignore_path.exists():
        dockerignore_text = dockerignore_path.read_text(encoding="utf-8", errors="replace")
        for required_pattern in ["CODE/RAG/storage", "**/model_cache", "CODE/Simulation/app/scenarios/results/*", "test-results"]:
            if required_pattern not in dockerignore_text:
                root_deployment_findings.append(f".dockerignore missing exclusion: {required_pattern}")
        for forbidden_pattern in ["CODE/RAG/quickstart", "CODE/Simulation/fixtures"]:
            if forbidden_pattern in dockerignore_text:
                root_deployment_findings.append(f".dockerignore excludes required quickstart input: {forbidden_pattern}")
    gitignore_path = ROOT / ".gitignore"
    if gitignore_path.exists() and "test-results/" not in gitignore_path.read_text(encoding="utf-8", errors="replace"):
        root_deployment_findings.append(".gitignore does not ignore test-results/")
    if ROOT_TEST_MATRIX.exists():
        try:
            test_matrix = json.loads((ROOT / ROOT_TEST_MATRIX).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            root_deployment_findings.append(f"test matrix cannot be parsed: {exc}")
        else:
            suites = test_matrix.get("suites", [])
            if not suites:
                root_deployment_findings.append("test matrix has no suites")
            for suite in suites:
                for field in ["working_directory", "junit_output"]:
                    value = str(suite.get(field, ""))
                    if Path(value).is_absolute() or re.search(r"^[A-Za-z]:[\\/]", value):
                        root_deployment_findings.append(f"test matrix uses absolute {field}: {suite.get('id')}")
                env_text = json.dumps(suite.get("environment", {}), sort_keys=True)
                if CREDENTIAL_BEARING_URL.search(env_text):
                    root_deployment_findings.append(f"test matrix has credential-bearing URL: {suite.get('id')}")
                if re.search(r"https?://100\.\d{1,3}\.\d{1,3}\.\d{1,3}|Tailscale", env_text, re.IGNORECASE):
                    root_deployment_findings.append(f"test matrix has external production/overlay URL: {suite.get('id')}")
    if ROOT_DOCKERFILE_TEST.exists():
        dockerfile_test = (ROOT / ROOT_DOCKERFILE_TEST).read_text(encoding="utf-8", errors="replace")
        if re.search(r"FROM\s+\S+:latest\b", dockerfile_test):
            root_deployment_findings.append("Dockerfile.test uses a latest base image")
        for forbidden in ["nvidia", "cuda", "vllm", "huggingface-cli", "sentence-transformers"]:
            if forbidden in dockerfile_test.lower():
                root_deployment_findings.append(f"Dockerfile.test appears to require model/GPU dependency: {forbidden}")
    if ROOT_COMPOSE_TEST.exists():
        try:
            compose_test = yaml.safe_load((ROOT / ROOT_COMPOSE_TEST).read_text(encoding="utf-8")) if yaml else None
        except Exception as exc:
            root_deployment_findings.append(f"docker-compose.test.yml cannot be parsed: {exc}")
            compose_test = None
        if compose_test:
            test_services = compose_test.get("services", {})
            if "test-runner" not in test_services:
                root_deployment_findings.append("docker-compose.test.yml lacks test-runner service")
            elif test_services["test-runner"].get("profiles") != ["test"]:
                root_deployment_findings.append("test-runner service is not profile-gated")
            if root_compose and "test-runner" in root_compose.get("services", {}):
                root_deployment_findings.append("production compose includes test-runner service")
    tracked_test_outputs = [
        path for path in tracked
        if path.startswith("test-results/") or path.endswith(".pytest.xml") or path.endswith(".junit.xml")
    ]
    if tracked_test_outputs:
        root_deployment_findings.append(f"test result/JUnit artifacts are tracked: {len(tracked_test_outputs)}")

    if root_deployment_findings:
        emit("FAIL", f"root quickstart deployment hygiene failures: {len(root_deployment_findings)}", counts)
        print_limited("root deployment findings", root_deployment_findings)
    else:
        emit("PASS", "root quickstart deployment files and safe defaults validate", counts)

    demo_findings = []
    for rel_path in [DEMO_SCENARIOS_JSON, DEMO_RUNNER_SCRIPT, DEMO_SCENARIOS_DOC]:
        if not (ROOT / rel_path).exists():
            demo_findings.append(f"missing required demo asset: {rel_path.as_posix()}")

    if (ROOT / DEMO_SCENARIOS_JSON).exists():
        try:
            scenario_payload = json.loads((ROOT / DEMO_SCENARIOS_JSON).read_text(encoding="utf-8"))
            scenarios = scenario_payload.get("scenarios", [])
        except (OSError, json.JSONDecodeError) as exc:
            demo_findings.append(f"demo scenario file is not valid JSON: {exc}")
            scenarios = []
        if not scenarios:
            demo_findings.append("demo scenarios list is empty")
        for scenario in scenarios:
            sid = scenario.get("id", "<unknown>")
            if "destructive" not in scenario or not isinstance(scenario.get("destructive"), bool):
                demo_findings.append(f"{sid}: destructive flag must be explicitly boolean")
            text = json.dumps(scenario, sort_keys=True)
            if ABS_LOCAL_PATH_PATTERN.search(text):
                demo_findings.append(f"{sid}: absolute local path detected in scenario")
            if CREDENTIAL_BEARING_URL.search(text):
                demo_findings.append(f"{sid}: credential-bearing URL detected in scenario")
            if re.search(r"https?://(?!localhost|127\.0\.0\.1|host\.docker\.internal|\[::1\])", text):
                demo_findings.append(f"{sid}: external URL target detected in scenario")
            lowered = text.lower()
            if "expected_prose" in lowered or "exact answer" in lowered:
                demo_findings.append(f"{sid}: exact prose assertions are forbidden")
            if re.search(r"live\s+simu5g\s*=\s*true|semantic\s*vector|gpu_required|llm_required\s*=\s*true", lowered):
                demo_findings.append(f"{sid}: scenario appears to require forbidden runtime capability")

    tracked_e2e_results = [path for path in tracked if path.startswith("e2e-results/")]
    if tracked_e2e_results:
        demo_findings.append(f"e2e-results artifacts are tracked: {len(tracked_e2e_results)}")
    gitignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="replace") if (ROOT / ".gitignore").exists() else ""
    if "e2e-results/" not in gitignore_text:
        demo_findings.append(".gitignore does not ignore e2e-results/")

    if demo_findings:
        emit("FAIL", f"Batch 9 demo scenario hygiene failures: {len(demo_findings)}", counts)
        print_limited("demo scenario findings", demo_findings)
    else:
        emit("PASS", "Batch 9 demo scenario assets and safety constraints validate", counts)

    contract_path = ROOT / SERVICE_CONTRACT
    if contract_path.exists():
        try:
            services = json.loads(contract_path.read_text(encoding="utf-8")).get("services", [])
        except (OSError, json.JSONDecodeError) as exc:
            emit("FAIL", f"service contract cannot be loaded: {exc}", counts)
            services = []
        ports = [service.get("host_port") for service in services]
        if ports and len(ports) == len(set(ports)):
            emit("PASS", "canonical service host ports are unique", counts)
        elif ports:
            emit("FAIL", "canonical service host ports contain duplicates", counts)
        expected_ports = {
            "simulation": 7000,
            "rag": 7001,
            "vllm": 8080,
            "gateway": 8888,
            "agent": 9090,
            "ui": 8501,
        }
        actual_ports = {service.get("name"): service.get("host_port") for service in services}
        if actual_ports == expected_ports:
            emit("PASS", "canonical service host ports match Batch 3 contract", counts)
        else:
            emit("FAIL", f"canonical service ports differ from Batch 3 contract: {actual_ports}", counts)
        simulation = next((service for service in services if service.get("name") == "simulation"), {})
        if simulation.get("readiness_path") == "/ready" and simulation.get("supported_modes") == ["replay", "live"]:
            emit("PASS", "Simulation service contract documents readiness and replay/live modes", counts)
        else:
            emit("FAIL", "Simulation service contract is missing readiness path or replay/live mode metadata", counts)
    else:
        emit("FAIL", f"service contract is absent: {SERVICE_CONTRACT.as_posix()}", counts)

    default_mode_findings = []
    fallback_findings = []
    for rel_path in SIMULATION_DEFAULT_EXAMPLES:
        path = ROOT / rel_path
        if not path.exists():
            default_mode_findings.append(f"{rel_path.as_posix()}: missing")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "SIMULATION_DEFAULT_MODE=replay" not in text and "SIMULATION_DEFAULT_MODE:-replay" not in text:
            default_mode_findings.append(f"{rel_path.as_posix()}: default mode is not documented as replay")
        if "LIVE_TO_REPLAY" in text.upper() or "FALLBACK_TO_REPLAY" in text.upper():
            fallback_findings.append(f"{rel_path.as_posix()}: contains silent fallback-looking flag")
    if default_mode_findings:
        emit("FAIL", f"Simulation submission examples do not consistently default to replay: {len(default_mode_findings)}", counts)
        print_limited("Simulation default findings", default_mode_findings)
    else:
        emit("PASS", "Simulation submission examples consistently default to CPU-safe replay mode", counts)
    if fallback_findings:
        emit("FAIL", f"Simulation configuration contains silent live-to-replay fallback-looking flags: {len(fallback_findings)}", counts)
        print_limited("Simulation fallback findings", fallback_findings)
    else:
        emit("PASS", "Simulation configuration exposes no silent live-to-replay fallback flag", counts)

    active_network_findings = []
    for rel_path in ACTIVE_NETWORK_CONFIG_FILES:
        path = ROOT / rel_path
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            active_network_findings.append(f"{rel_path.as_posix()}: unreadable: {exc}")
            continue
        for pattern in FORBIDDEN_ACTIVE_NETWORK_PATTERNS:
            if pattern.search(text):
                active_network_findings.append(f"{rel_path.as_posix()}: {pattern.pattern}")
    if active_network_findings:
        emit("FAIL", f"active/default network configuration still contains Tailscale or 100.x URLs: {len(active_network_findings)}", counts)
        print_limited("active network findings", active_network_findings)
    else:
        emit("PASS", "active/default network configuration has no Tailscale or 100.x URL dependency", counts)

    disposable = [
        Path("CODE/Simulation/.cmdenv-log"),
        Path("CODE/Simulation/simu5g.tar.gz"),
        Path("CODE/Agent/rough.txt"),
        Path("CODE/RAG/rough.txt"),
        Path("CODE/Simulation/rough.txt"),
    ]
    remaining_tracked_empty = []
    for item in disposable:
        path = ROOT / item
        if item.as_posix() in tracked and path.exists() and path.is_file() and path.stat().st_size == 0:
            remaining_tracked_empty.append(item.as_posix())
    if remaining_tracked_empty:
        emit("FAIL", f"approved empty disposable tracked artifacts remain in working tree: {len(remaining_tracked_empty)}", counts)
        print_limited("remaining disposable paths", remaining_tracked_empty)
    else:
        emit("PASS", "approved empty disposable tracked artifacts are absent from working tree", counts)

    emit("WARN", "full live Simu5G execution has not been validated by the hygiene script", counts)
    emit("WARN", "full semantic RAG clean-machine execution has not been validated by the hygiene script", counts)
    emit("WARN", "optional vLLM runtime remains untested by the hygiene script", counts)
    emit("WARN", "OPEA integration is interface-level unless separately validated end to end", counts)
    emit("WARN", "formal four-core quickstart timing remains pending", counts)
    emit("PASS", "quickstart-oriented Simulation replay mode has explicit fixture validation checks", counts)

    if not (ROOT / "docker-compose.yml").exists() and not (ROOT / "deploy.sh").exists():
        emit("WARN", "missing root one-click quickstart entry point", counts)

    print(f"SUMMARY PASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
