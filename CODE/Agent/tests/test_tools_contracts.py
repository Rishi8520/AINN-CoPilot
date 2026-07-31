import importlib
import json
import sys
from pathlib import Path

import pytest
import requests


AGENT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = AGENT_ROOT / "tools"
sys.path.insert(0, str(TOOLS_ROOT))
sys.path.insert(1, str(AGENT_ROOT))


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text or ("" if isinstance(payload, Exception) else json.dumps(payload))

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


@pytest.fixture()
def tools_module(monkeypatch):
    for name in [
        "SIMULATION_BASE_URL",
        "SIM_SERVICE_URL",
        "RAG_BASE_URL",
        "RAG_SERVICE_URL",
    ]:
        monkeypatch.delenv(name, raising=False)
    sys.modules.pop("tools", None)
    return importlib.import_module("tools")


def test_agent_service_url_defaults_are_canonical_and_normalized(tools_module, monkeypatch):
    assert tools_module._base_url_from_env(
        "SIMULATION_BASE_URL",
        "SIM_SERVICE_URL",
        "http://localhost:7000",
    ) == "http://localhost:7000"

    monkeypatch.delenv("SIMULATION_BASE_URL", raising=False)
    monkeypatch.setenv("SIM_SERVICE_URL", " http://legacy-simulation:7000/ ")
    assert tools_module._base_url_from_env(
        "SIMULATION_BASE_URL",
        "SIM_SERVICE_URL",
        "http://localhost:7000",
    ) == "http://legacy-simulation:7000"

    monkeypatch.setenv("SIMULATION_BASE_URL", " http://simulation:7000/ ")
    monkeypatch.setenv("SIM_SERVICE_URL", " http://legacy-simulation:7000/ ")
    assert tools_module._base_url_from_env(
        "SIMULATION_BASE_URL",
        "SIM_SERVICE_URL",
        "http://localhost:7000",
    ) == "http://simulation:7000"

    monkeypatch.setenv("SIMULATION_BASE_URL", "")
    monkeypatch.delenv("SIM_SERVICE_URL", raising=False)
    assert tools_module._base_url_from_env(
        "SIMULATION_BASE_URL",
        "SIM_SERVICE_URL",
        "http://localhost:7000",
    ) == "http://localhost:7000"


def test_agent_and_gateway_url_precedence(monkeypatch):
    for module_name in ["agent", "gateway"]:
        sys.modules.pop(module_name, None)

    import agent
    import gateway

    monkeypatch.setenv("AGENT_BASE_URL", " http://agent:9090/ ")
    monkeypatch.setenv("AGENT_ENDPOINT", " http://legacy-agent:9090/ ")
    assert agent._base_url_from_env(
        "AGENT_BASE_URL",
        "AGENT_ENDPOINT",
        "http://agent:9090",
    ) == "http://agent:9090"
    assert gateway._base_url_from_env(
        "AGENT_BASE_URL",
        "AGENT_ENDPOINT",
        "http://agent:9090",
    ) == "http://agent:9090"

    monkeypatch.setenv("AGENT_BASE_URL", "")
    assert agent._base_url_from_env(
        "AGENT_BASE_URL",
        "AGENT_ENDPOINT",
        "http://agent:9090",
    ) == "http://legacy-agent:9090"

def test_call_simulation_sends_canonical_json_body(tools_module, monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "run_id": "run-1",
                "status": "accepted",
                "mode": "live",
                "requested_parameters": json,
                "applied_parameters": {"mode": "live"},
                "unsupported_parameters": {
                    "cell_id": "Accepted as metadata only in Batch 3.",
                    "slice_type": "Accepted as metadata only in Batch 3.",
                },
                "metrics": {},
                "result_reference": {"current_phase": "phase_01_normal"},
                "error": None,
            }
        )

    monkeypatch.setenv("SIMULATION_BASE_URL", "http://simulation:7000/")
    monkeypatch.setattr(tools_module.requests, "post", fake_post)

    result = json.loads(
        tools_module.call_simulation(
            "baseline",
            ue_count=20,
            cell_id=3,
            slice_type="URLLC",
        )
    )

    assert captured["url"] == "http://simulation:7000/simulate"
    assert captured["json"] == {
        "scenario": "normal_operation",
        "ue_count": 20,
        "cell_id": 3,
        "slice_type": "URLLC",
        "mode": "live",
    }
    assert captured["timeout"] == 120
    assert result["status"] == "accepted"
    assert result["unsupported_parameters"]["cell_id"]
    assert result["unsupported_parameters"]["slice_type"]


def test_call_simulation_preserves_response_status_without_fake_success(tools_module, monkeypatch):
    def fake_post(url, json, timeout):
        return FakeResponse(
            {
                "run_id": "run-2",
                "status": "failed",
                "mode": "live",
                "requested_parameters": json,
                "applied_parameters": {},
                "unsupported_parameters": {},
                "metrics": {},
                "result_reference": {},
                "error": {"code": "simulation_runner_not_running"},
            }
        )

    monkeypatch.setattr(tools_module.requests, "post", fake_post)

    result = json.loads(tools_module.call_simulation("baseline"))

    assert result["status"] == "failed"
    assert result["metrics"] == {}
    assert result["error"]["code"] == "simulation_runner_not_running"


def test_call_simulation_handles_error_cases(tools_module, monkeypatch):
    def timeout_post(*args, **kwargs):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(tools_module.requests, "post", timeout_post)
    assert json.loads(tools_module.call_simulation("baseline"))["error"].startswith("Simulation timed out")

    def malformed_post(*args, **kwargs):
        return FakeResponse(ValueError("not json"))

    monkeypatch.setattr(tools_module.requests, "post", malformed_post)
    assert json.loads(tools_module.call_simulation("baseline"))["error"] == "Simulation service returned malformed JSON."

    def non_2xx_post(*args, **kwargs):
        return FakeResponse({"detail": "bad"}, status_code=503, text="service down")

    monkeypatch.setattr(tools_module.requests, "post", non_2xx_post)
    assert "HTTP 503" in json.loads(tools_module.call_simulation("baseline"))["error"]


def test_call_rag_uses_structured_json_endpoint(tools_module, monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "query": "handover",
                "answer_context": "",
                "sources": [],
                "raw": {"result_count": 0},
            }
        )

    monkeypatch.setenv("RAG_BASE_URL", "http://rag:7001/")
    monkeypatch.setattr(tools_module.requests, "post", fake_post)

    result = json.loads(tools_module.call_rag("handover"))

    assert captured["url"] == "http://rag:7001/v1/retrievaltool/json"
    assert captured["json"] == {"text": "handover"}
    assert captured["timeout"] == 30
    assert result["raw"]["result_count"] == 0


def test_call_rag_handles_malformed_and_service_failure(tools_module, monkeypatch):
    def malformed_post(*args, **kwargs):
        return FakeResponse(ValueError("not json"))

    monkeypatch.setattr(tools_module.requests, "post", malformed_post)
    assert json.loads(tools_module.call_rag("handover"))["error"] == "RAG service returned malformed JSON."

    def non_2xx_post(*args, **kwargs):
        return FakeResponse({"detail": "bad"}, status_code=500, text="service failed")

    monkeypatch.setattr(tools_module.requests, "post", non_2xx_post)
    assert "HTTP 500" in json.loads(tools_module.call_rag("handover"))["error"]


def test_call_rag_canonical_base_url_wins_over_legacy(tools_module, monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        return FakeResponse(
            {
                "query": json["text"],
                "answer_context": "",
                "sources": [
                    {
                        "source": "spec.pdf",
                        "title": "Spec",
                        "section": "1",
                        "chunk": 2,
                        "page": 3,
                        "kind": "spec",
                        "source_type": "spec",
                    }
                ],
                "raw": {"result_count": 1},
            }
        )

    monkeypatch.setenv("RAG_BASE_URL", "http://rag:7001/")
    monkeypatch.setenv("RAG_SERVICE_URL", "http://legacy-rag:7001/")
    monkeypatch.setattr(tools_module.requests, "post", fake_post)

    result = json.loads(tools_module.call_rag("handover"))

    assert captured["url"] == "http://rag:7001/v1/retrievaltool/json"
    assert result["sources"][0]["source"] == "spec.pdf"
    assert result["sources"][0]["chunk"] == 2
    assert result["sources"][0]["page"] == 3
    assert result["sources"][0]["kind"] == "spec"
    assert result["sources"][0]["source_type"] == "spec"
