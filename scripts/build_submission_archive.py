#!/usr/bin/env python3
"""Build the TelcoMind submission archive from Git-tracked files.

Standard-library only. Produces:
  dist/AINN-CoPilot-submission.zip
  dist/AINN-CoPilot-submission.zip.sha256

Rules:
- Archive contents are derived from Git-tracked files only.
- Generated results, caches, virtual envs, secrets, local .env files, and existing
  archives are excluded.
- Third-party standards PDFs are excluded unless redistribution permission is explicitly
  established via the ALLOW_STANDARDS_PDFS environment flag.
- TECHNICAL_REPORT.pdf is retained when present (even though it may be untracked).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
ARCHIVE = DIST / "AINN-CoPilot-submission.zip"
CHECKSUM = DIST / "AINN-CoPilot-submission.zip.sha256"

ALLOW_STANDARDS_PDFS = os.getenv("ALLOW_STANDARDS_PDFS", "").lower() in {"1", "true", "yes"}

EXCLUDE_PREFIXES = (
    ".git/",
    "dist/",
    "e2e-results/",
    "test-results/",
    "performance-results/",
)
EXCLUDE_DIR_PARTS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules",
}
EXCLUDE_NAMES = {".env"}

MANDATORY_INSIDE = [
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "TECHNICAL_REPORT.md",
    "docker-compose.yml",
    "deploy.ps1",
    "deploy.sh",
    "test.ps1",
    "test.sh",
    "demo/quickstart_scenarios.json",
    "scripts/run_demo_scenarios.py",
]


def git_tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, stdout=subprocess.PIPE,
                         text=True, check=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


def is_standards_pdf(rel: str) -> bool:
    if not rel.lower().endswith(".pdf"):
        return False
    lowered = rel.lower()
    return any(tag in lowered for tag in ("3gpp", "etsi", "o-ran", "oran", "standard", "spec"))


def excluded(rel: str) -> bool:
    posix = rel.replace("\\", "/")
    if any(posix.startswith(p) for p in EXCLUDE_PREFIXES):
        return True
    parts = set(Path(posix).parts)
    if parts & EXCLUDE_DIR_PARTS:
        return True
    if Path(posix).name in EXCLUDE_NAMES:
        return True
    if posix.endswith(".zip") or posix.endswith(".zip.sha256"):
        return True
    if is_standards_pdf(posix) and not ALLOW_STANDARDS_PDFS:
        return True
    return False


def build() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.exists():
        ARCHIVE.unlink()

    members: list[tuple[Path, str]] = []
    for rel in git_tracked():
        if excluded(rel):
            continue
        abs_path = ROOT / rel
        if abs_path.exists():
            members.append((abs_path, rel))

    # Retain the generated technical report PDF even if untracked.
    pdf = ROOT / "TECHNICAL_REPORT.pdf"
    if pdf.exists() and not any(rel == "TECHNICAL_REPORT.pdf" for _, rel in members):
        members.append((pdf, "TECHNICAL_REPORT.pdf"))

    members.sort(key=lambda item: item[1])

    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for abs_path, rel in members:
            zf.write(abs_path, arcname=rel)

    data = ARCHIVE.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    CHECKSUM.write_text(f"{digest}  {ARCHIVE.name}\n", encoding="utf-8")

    # Verify the archive opens and mandatory files exist inside it.
    with zipfile.ZipFile(ARCHIVE, "r") as zf:
        bad = zf.testzip()
        if bad is not None:
            print(f"FAIL corrupt entry: {bad}")
            return 1
        names = set(zf.namelist())

    missing = [m for m in MANDATORY_INSIDE if m not in names]
    if missing:
        print("FAIL missing mandatory files inside archive: " + ", ".join(missing))
        return 1

    print(f"PASS archive built: {ARCHIVE.relative_to(ROOT)}")
    print(f"PASS entries: {len(names)}")
    print(f"PASS sha256: {digest}")
    print(f"PASS checksum file: {CHECKSUM.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(build())
