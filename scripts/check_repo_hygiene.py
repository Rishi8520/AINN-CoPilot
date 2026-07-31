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
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIM_RESULTS = Path("CODE/Simulation/app/scenarios/results")
SIM_GENERATED = Path("CODE/Simulation/app/scenarios/generated")
SIM_FIXTURES = Path("CODE/Simulation/fixtures/replay")
SIM_FIXTURE_MANIFEST = SIM_FIXTURES / "phase_bootstrap_normal" / "manifest.json"
ALLOWED_RUNTIME_TRACKED = {"README.md", ".gitkeep"}
RAG_CHROMA = Path("CODE/RAG/storage/chroma")
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
]
TRACKED_CACHE_PATTERNS = [
    "*/__pycache__/*",
    "__pycache__/*",
    "*.pyc",
    "*.pyo",
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

    for filename in REQUIRED_ROOT_FILES:
        path = ROOT / filename
        if path.exists():
            emit("PASS", f"required root file present: {filename}", counts)
        else:
            emit("WARN", f"future submission deliverable missing at root: {filename}", counts)

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
    emit("WARN", "quickstart/replay mode implementation remains a later-batch validation item", counts)

    if not (ROOT / "docker-compose.yml").exists() and not (ROOT / "deploy.sh").exists():
        emit("WARN", "missing root one-click quickstart entry point", counts)

    print(f"SUMMARY PASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
