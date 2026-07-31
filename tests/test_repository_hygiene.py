import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_repository_hygiene_validator_passes_without_failures():
    result = subprocess.run(
        [sys.executable, "scripts/check_repo_hygiene.py"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert result.returncode == 0, result.stdout
    assert "\nFAIL " not in "\n" + result.stdout
    assert "SUMMARY " in result.stdout
