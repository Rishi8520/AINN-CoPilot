import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run_demo_scenarios.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("run_demo_scenarios", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _base_scenario() -> dict:
    return {
        "id": "grounded_diagnosis",
        "title": "x",
        "purpose": "x",
        "category": "hybrid",
        "gateway_request": {"query": "q", "stream": False},
        "expected_services": ["gateway", "agent", "simulation", "rag", "synthesis"],
        "expected_http_status": 200,
        "required_response_fields": ["id", "status", "simulation", "rag", "synthesis", "evidence", "choices"],
        "forbidden_claims": [],
        "expected_provenance": {
            "fixture_id": "phase_bootstrap_normal",
            "mode_label": "recorded_replay",
            "checksums_verified": True,
            "created_from_existing_repository_artifact": True,
        },
        "expected_source_types": ["runbook"],
        "expected_simulation_mode": "replay",
        "expected_rag_profile": "quickstart",
        "expected_retrieval_backend": "lexical_bm25",
        "expected_synthesis_backend": "deterministic",
        "allow_empty_retrieval": False,
        "timeout_seconds": 30,
        "destructive": False,
        "notes": "x",
    }


def _good_record() -> dict:
    return {
        "http_status": 200,
        "duration_seconds": 0.1,
        "body": {
            "id": "telcomind-quickstart-t",
            "status": "completed",
            "choices": [],
            "evidence": {
                "simulation_reached": True,
                "rag_reached": True,
                "simulation_mode": "replay",
            },
            "simulation": {
                "run_id": "replay-phase_bootstrap_normal-rid",
                "status": "completed",
                "mode": "replay",
                "metrics": {"aggregate": {"throughput_mbps": 2.15}},
                "unsupported_parameters": {"ue_count": "not applied"},
                "result_reference": {
                    "mode_label": "recorded_replay",
                    "live_simulation": False,
                    "provenance": {
                        "fixture_id": "phase_bootstrap_normal",
                        "checksums_verified": True,
                        "created_from_existing_repository_artifact": True,
                    },
                },
            },
            "rag": {
                "rag_profile": "quickstart",
                "retrieval_backend": "lexical_bm25",
                "result_count": 1,
                "raw": {"score_type": "bm25_raw"},
                "sources": [
                    {
                        "id": "qs-handover-failure-runbook-handover-failure-01",
                        "source": "knowledge_base/runbooks/handover_failure_runbook.json",
                        "title": "Handover Failure Runbook",
                        "section": "handover_failure",
                        "chunk": 1,
                        "page": None,
                        "kind": "runbook",
                        "source_type": "runbook",
                    }
                ],
            },
            "synthesis": {
                "synthesis_backend": "deterministic",
                "llm_used": False,
                "fallback_used": False,
                "unknown_citation_ids": [],
                "citations": [
                    {
                        "citation_id": "C1",
                        "source": "knowledge_base/runbooks/handover_failure_runbook.json",
                        "title": "Handover Failure Runbook",
                        "section": "handover_failure",
                        "chunk": 1,
                        "page": None,
                        "kind": "runbook",
                        "source_type": "runbook",
                    }
                ],
            },
        },
    }


def test_validate_base_url_rejects_external_targets():
    runner = _load_runner_module()
    with pytest.raises(runner.ScenarioError):
        runner._validate_base_url_or_raise("https://example.com")


def test_output_dir_must_stay_under_e2e_results(tmp_path):
    runner = _load_runner_module()
    with pytest.raises(runner.ScenarioError):
        runner._resolve_output_dir(tmp_path, "outside-results")


def test_list_mode_does_not_require_stack(monkeypatch, tmp_path):
    runner = _load_runner_module()

    scenario_file = tmp_path / "demo" / "quickstart_scenarios.json"
    scenario_file.parent.mkdir(parents=True)
    scenario_file.write_text(json.dumps({"scenarios": [_base_scenario()]}), encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    monkeypatch.setattr(runner, "DEFAULT_SCENARIO_FILE", Path("demo/quickstart_scenarios.json"))
    monkeypatch.setattr(runner, "find_repo_root", lambda start: tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_demo_scenarios.py", "--list"])

    assert runner.main() == 0


def test_default_selection_excludes_destructive():
    runner = _load_runner_module()
    one = _base_scenario()
    two = dict(_base_scenario())
    two["id"] = "destructive_case"
    two["destructive"] = True

    selected = runner._scenario_ids_to_run([one, two], one=None, include_destructive=False)
    assert [item["id"] for item in selected] == ["grounded_diagnosis"]


def test_structural_validation_passes_for_valid_response():
    runner = _load_runner_module()
    scenario = _base_scenario()
    record = _good_record()

    runner._validate_scenario_result(scenario, record)


def test_false_live_simu5g_claim_fails():
    runner = _load_runner_module()
    scenario = _base_scenario()
    record = _good_record()
    record["body"]["synthesis"]["answer"] = "live Simu5G executed successfully"

    with pytest.raises(runner.ScenarioError):
        runner._validate_scenario_result(scenario, record)


def test_false_llm_used_claim_fails():
    runner = _load_runner_module()
    scenario = _base_scenario()
    record = _good_record()
    record["body"]["synthesis"]["llm_used"] = True

    with pytest.raises(runner.ScenarioError):
        runner._validate_scenario_result(scenario, record)


def test_false_semantic_backend_claim_fails():
    runner = _load_runner_module()
    scenario = _base_scenario()
    record = _good_record()
    record["body"]["rag"]["retrieval_backend"] = "semantic_vector"

    with pytest.raises(runner.ScenarioError):
        runner._validate_scenario_result(scenario, record)


def test_confidence_labeled_bm25_fails():
    runner = _load_runner_module()
    scenario = _base_scenario()
    record = _good_record()
    record["body"]["rag"]["raw"]["score_type"] = "confidence"

    with pytest.raises(runner.ScenarioError):
        runner._validate_scenario_result(scenario, record)


def test_unknown_citation_fails():
    runner = _load_runner_module()
    scenario = _base_scenario()
    record = _good_record()
    record["body"]["synthesis"]["unknown_citation_ids"] = ["C99"]

    with pytest.raises(runner.ScenarioError):
        runner._validate_scenario_result(scenario, record)


def test_unsupported_fault_mapped_to_baseline_fails():
    runner = _load_runner_module()
    scenario = _base_scenario()
    scenario["id"] = "unsupported_replay_fault"
    scenario["expected_http_status"] = 200
    scenario["gateway_request"]["query"] = "simulate handover_failure replay mode"

    record = _good_record()
    record["body"]["simulation"]["requested_parameters"] = {"scenario": "baseline"}

    with pytest.raises(runner.ScenarioError):
        runner._validate_scenario_result(scenario, record)


def test_redaction_removes_credentials_and_absolute_paths():
    runner = _load_runner_module()
    value = {
        "url": "https://user:pass@example.com/v1/chat/completions",
        "Authorization": "Bearer abc",
        "path": "C:\\Users\\someone\\secret.txt",
    }
    redacted = runner._redact_obj(value)

    assert "user:pass" not in json.dumps(redacted)
    assert "Bearer" not in json.dumps(redacted)
    assert "C:\\Users\\someone" not in json.dumps(redacted)


def test_failed_required_scenario_returns_nonzero(monkeypatch, tmp_path):
    runner = _load_runner_module()

    scenario = _base_scenario()
    scenario_file = tmp_path / "demo" / "quickstart_scenarios.json"
    scenario_file.parent.mkdir(parents=True)
    scenario_file.write_text(json.dumps({"scenarios": [scenario]}), encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    monkeypatch.setattr(runner, "DEFAULT_SCENARIO_FILE", Path("demo/quickstart_scenarios.json"))
    monkeypatch.setattr(runner, "find_repo_root", lambda start: tmp_path)
    monkeypatch.setattr(runner, "_current_commit", lambda root: "deadbeef")
    monkeypatch.setattr(runner, "_stack_health", lambda root, base_url, timeout: {"healthy_enough": True})
    monkeypatch.setattr(
        runner,
        "_run_gateway_scenario",
        lambda base_url, scenario, timeout: {
            "scenario_id": scenario["id"],
            "http_status": 500,
            "duration_seconds": 0.1,
            "body": {"detail": "failed"},
        },
    )
    monkeypatch.setattr(sys, "argv", ["run_demo_scenarios.py", "--output-dir", str(tmp_path / "e2e-results")])

    assert runner.main() == 1


def test_failure_injection_restoration_happens_in_finally(monkeypatch, tmp_path):
    runner = _load_runner_module()

    calls = []

    def fake_compose_service(root, action, service):
        calls.append((action, service))
        return 0, "ok"

    monkeypatch.setattr(runner, "_compose_service", fake_compose_service)
    monkeypatch.setattr(runner, "_wait_service_healthy", lambda root, service, timeout: True)
    monkeypatch.setattr(runner, "_service_log_snapshot", lambda root, service, output: None)
    monkeypatch.setattr(
        runner,
        "_load_scenarios",
        lambda path: {"scenarios": [_base_scenario()]},
    )

    def fake_run_gateway(base_url, scenario, timeout):
        # While dependency is down return non-success; recovery checks return success.
        if calls and calls[-1][0] == "stop":
            return {"http_status": 502, "duration_seconds": 0.1, "body": {"detail": "down"}}
        return _good_record()

    monkeypatch.setattr(runner, "_run_gateway_scenario", fake_run_gateway)
    monkeypatch.setattr(runner, "_validate_scenario_result", lambda scenario, record: None)

    result = runner._failure_injection(tmp_path, "http://localhost:8888", 5, tmp_path / "e2e-results", False)

    assert result["enabled"] is True
    assert ("stop", "rag") in calls
    assert ("start", "rag") in calls
    assert ("stop", "simulation") in calls
    assert ("start", "simulation") in calls
