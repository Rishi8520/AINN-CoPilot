#!/usr/bin/env python3
"""Final submission audit for the TelcoMind package.

Standard-library only. Prints PASS/WARN/FAIL lines and returns a nonzero exit code
only when a mandatory check fails.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIDEO_URL = "https://drive.google.com/drive/folders/1HTGxiuk3dk1el6hzPPlSq3WNEocslcdc?usp=drive_link"

failures: list[str] = []
warnings: list[str] = []


def _p(status: str, name: str, detail: str = "") -> None:
    line = f"{status} {name}"
    if detail:
        line += f": {detail}"
    print(line)


def mandatory(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        _p("PASS", name)
    else:
        failures.append(name)
        _p("FAIL", name, detail)


def advisory(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        _p("PASS", name)
    else:
        warnings.append(name)
        _p("WARN", name, detail)


def read(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, timeout=30)
        return out.stdout
    except Exception:
        return ""


def main() -> int:
    required_files = [
        "README.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "TECHNICAL_REPORT.md",
        "SUBMISSION_MANIFEST.json",
        "FINAL_SUBMISSION_CHECKLIST.md",
        "docker-compose.yml",
        "deploy.ps1",
        "deploy.sh",
        "test.ps1",
        "test.sh",
        "demo/quickstart_scenarios.json",
        "scripts/run_demo_scenarios.py",
    ]
    for rel in required_files:
        mandatory(f"required file present: {rel}", (ROOT / rel).exists())

    # Technical report PDF is desirable but not mandatory.
    pdf = ROOT / "TECHNICAL_REPORT.pdf"
    if pdf.exists() and pdf.stat().st_size > 0:
        _p("PASS", "TECHNICAL_REPORT.pdf present", f"{pdf.stat().st_size} bytes")
    else:
        advisory("TECHNICAL_REPORT.pdf present", False, "PDF export pending")

    readme = read("README.md")
    mandatory("README contains exact demo video folder URL", VIDEO_URL in readme)
    for token in ("recorded replay", "lexical bm25", "deterministic"):
        mandatory(f"README states truthful limitation: {token}",
                  token in readme.lower())

    # Manifest JSON valid and free of absolute Windows paths.
    manifest_text = read("SUBMISSION_MANIFEST.json")
    try:
        json.loads(manifest_text)
        mandatory("SUBMISSION_MANIFEST.json parses", True)
    except Exception as exc:
        mandatory("SUBMISSION_MANIFEST.json parses", False, str(exc))
    mandatory("manifest has no absolute Windows path",
              re.search(r"[A-Za-z]:\\\\", manifest_text) is None
              and not re.search(r"[A-Za-z]:\\", manifest_text))

    # Demo scenario JSON valid.
    scen = read("demo/quickstart_scenarios.json")
    try:
        json.loads(scen)
        mandatory("demo/quickstart_scenarios.json parses", True)
    except Exception as exc:
        mandatory("demo/quickstart_scenarios.json parses", False, str(exc))

    tracked = [line for line in git("ls-files").splitlines() if line.strip()]

    # No tracked .env file (examples/templates allowed).
    env_tracked = [f for f in tracked
                   if Path(f).name == ".env" or f.endswith("/.env")]
    mandatory("no tracked .env file", not env_tracked,
              ", ".join(env_tracked))

    # e2e-results and test-results must not be tracked.
    generated_tracked = [f for f in tracked
                         if f.startswith("e2e-results/") or f.startswith("test-results/")
                         or f.startswith("dist/") or f.startswith("performance-results/")]
    # README/.gitkeep placeholders are acceptable.
    generated_tracked = [f for f in generated_tracked
                        if Path(f).name not in {"README.md", ".gitkeep"}]
    advisory("no generated result artifacts tracked", not generated_tracked,
             ", ".join(generated_tracked[:5]))

    # No active Tailscale / 100.x defaults in active config surfaces.
    active_files = [
        ".env.example", "docker-compose.yml", "CODE/.env.example",
        "CODE/Agent/tools/tools.py", "CODE/Agent/agent.py", "CODE/Agent/gateway.py",
        "CODE/Agent/ui/app.py", "CODE/Agent/docker-compose.yml",
        "CODE/RAG/docker-compose.yml", "CODE/Simulation/docker-compose.yml",
    ]
    tail = re.compile(r"https?://100\.\d{1,3}\.\d{1,3}\.\d{1,3}|tailscale", re.IGNORECASE)
    tail_hits = [f for f in active_files if (ROOT / f).exists() and tail.search(read(f))]
    mandatory("no active Tailscale/100.x defaults", not tail_hits, ", ".join(tail_hits))

    # No obvious credential values in active configuration.
    secret = re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?([A-Za-z0-9_./+\-]{16,})")
    secret_hits = []
    for f in active_files:
        if not (ROOT / f).exists():
            continue
        for m in secret.finditer(read(f)):
            val = m.group(2)
            if val.startswith(("config.", "os.getenv", "getenv", "env.")):
                continue
            secret_hits.append(f)
            break
    mandatory("no credential values in active configuration", not secret_hits,
              ", ".join(secret_hits))

    # git diff --check clean.
    diff_check = git("diff", "--check")
    actionable = [ln for ln in diff_check.splitlines()
                  if "trailing whitespace" in ln or "conflict marker" in ln]
    advisory("git diff --check clean (no whitespace errors)", not actionable,
             f"{len(actionable)} issues")

    print()
    if failures:
        print(f"SUMMARY FAIL mandatory_failures={len(failures)} warnings={len(warnings)}")
        return 1
    print(f"SUMMARY PASS mandatory_failures=0 warnings={len(warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
