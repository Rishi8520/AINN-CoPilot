import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "demo" / "quickstart_scenarios.json"


REQUIRED_SCENARIOS = {
    "grounded_diagnosis",
    "standards_question",
    "runbook_kpi_question",
    "scenario_mapping_question",
    "out_of_scope_no_match",
    "unsupported_replay_fault",
    "malformed_request",
    "deterministic_repeatability",
}

REQUIRED_FIELDS = {
    "id",
    "title",
    "purpose",
    "category",
    "gateway_request",
    "expected_services",
    "expected_http_status",
    "required_response_fields",
    "forbidden_claims",
    "expected_provenance",
    "expected_simulation_mode",
    "expected_rag_profile",
    "expected_retrieval_backend",
    "expected_synthesis_backend",
    "allow_empty_retrieval",
    "timeout_seconds",
    "destructive",
    "notes",
}


def test_scenario_json_parses_and_contains_required_ids():
    payload = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    scenarios = payload["scenarios"]
    ids = {item["id"] for item in scenarios}

    assert REQUIRED_SCENARIOS.issubset(ids)
    assert len(ids) == len(scenarios)


def test_scenarios_have_required_fields_and_no_absolute_paths_or_secrets():
    payload = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    absolute = re.compile(r"[A-Za-z]:\\|/Users/|/home/")
    secret = re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s]+")
    external_url = re.compile(r"https?://(?!localhost|127\.0\.0\.1|host\.docker\.internal|\[::1\])")

    for scenario in payload["scenarios"]:
        missing = REQUIRED_FIELDS - set(scenario)
        assert not missing, (scenario["id"], sorted(missing))

        text = json.dumps(scenario, sort_keys=True)
        assert absolute.search(text) is None, scenario["id"]
        assert secret.search(text) is None, scenario["id"]
        assert external_url.search(text) is None, scenario["id"]


def test_destructive_marking_and_no_exact_prose_expectations():
    payload = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    for scenario in payload["scenarios"]:
        assert isinstance(scenario["destructive"], bool)
        lowered = json.dumps(scenario, sort_keys=True).lower()
        assert "expected_prose" not in lowered
        assert "exact answer" not in lowered
        assert "must equal" not in lowered


def test_scenarios_do_not_require_forbidden_runtime_modes():
    payload = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    forbidden = ["live simu5g", "semantic", "vector retrieval", "gpu", "vllm", "openai"]
    for scenario in payload["scenarios"]:
        text = json.dumps(scenario, sort_keys=True).lower()
        # Scenario text may mention forbidden capabilities only as negatives/forbidden claims.
        if "forbidden_claims" in scenario:
            clean = text
            for claim in scenario["forbidden_claims"]:
                clean = clean.replace(claim.lower(), "")
        else:
            clean = text
        for token in forbidden:
            assert f'"requires_{token}"' not in clean
