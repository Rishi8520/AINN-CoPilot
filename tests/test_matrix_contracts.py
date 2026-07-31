import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "tests" / "test_matrix.json"
RUNNER = ROOT / "scripts" / "run_test_matrix.py"


def _probe(component: str) -> str:
    cwd = ROOT / "CODE" / component
    env = os.environ.copy()
    env["PYTHONPATH"] = str(cwd)
    code = "import app, pathlib; print(pathlib.Path(app.__file__).resolve().as_posix())"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def test_matrix_is_structured_and_uses_relative_paths():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    ids = [suite["id"] for suite in matrix["suites"]]

    assert ids == [
        "root_contracts",
        "agent",
        "rag_core",
        "rag_synthesis",
        "simulation",
        "repository_hygiene",
        "artifact_integrity",
        "static_configuration",
        "optional_smoke",
    ]
    for suite in matrix["suites"]:
        assert isinstance(suite["args"], list)
        assert not Path(suite["working_directory"]).is_absolute()
        assert not Path(suite["junit_output"]).is_absolute()
        assert "shell" not in suite
        assert suite["separate_process"] is True


def test_collision_prone_suites_are_not_grouped_in_one_process():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    risky = {suite["id"]: suite for suite in matrix["suites"] if suite["import_collision_risk"] == "high"}

    assert set(risky) == {"rag_core", "rag_synthesis", "simulation"}
    for suite in risky.values():
        assert suite["runner"] == "pytest"
        assert suite["working_directory"] in {"CODE/RAG", "CODE/Simulation"}
        assert suite["pythonpath"] == ["."]


def test_rag_and_simulation_import_their_own_app_packages():
    rag_app = _probe("RAG")
    sim_app = _probe("Simulation")

    assert "/CODE/RAG/app/__init__.py" in rag_app
    assert "/CODE/Simulation/app/__init__.py" in sim_app
    assert rag_app != sim_app


def test_rag_simulation_probe_order_is_independent():
    first = [_probe("RAG"), _probe("Simulation")]
    second = [_probe("Simulation"), _probe("RAG")]

    assert first[0] == second[1]
    assert first[1] == second[0]


def test_parent_sys_modules_cannot_contaminate_child_imports(monkeypatch):
    class FakeApp:
        __file__ = "parent-only-app"

    monkeypatch.setitem(sys.modules, "app", FakeApp())

    assert "/CODE/RAG/app/__init__.py" in _probe("RAG")
    assert "/CODE/Simulation/app/__init__.py" in _probe("Simulation")


def test_no_root_monolithic_pytest_command_is_advertised_for_collision_suites():
    runner_text = RUNNER.read_text(encoding="utf-8")

    assert "pytest tests CODE/RAG/tests CODE/Simulation/tests" not in runner_text
    assert "subprocess.Popen" in runner_text
    assert "shell=False" in runner_text


def test_matrix_list_command_runs_without_component_imports():
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--list"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert "rag_core" in result.stdout
    assert "simulation" in result.stdout
    assert "Traceback" not in result.stderr


def test_offline_network_policy_blocks_external_http():
    request = urllib.request.Request("http://example.com/", headers={"User-Agent": "telcomind-offline-test"})
    try:
        urllib.request.urlopen(request, timeout=2)
    except (OSError, urllib.error.URLError, TimeoutError):
        return
    raise AssertionError("external HTTP unexpectedly succeeded during an offline required suite")
