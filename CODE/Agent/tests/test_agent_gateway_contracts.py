import asyncio
import importlib
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException, Response


AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))


class FakeResponse:
    def __init__(self, payload, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if text is None else text
        self.request = httpx.Request("POST", "http://fake.local")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("downstream failed", request=self.request, response=httpx.Response(self.status_code, text=self.text))


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        return FakeResponse({"ready": True, "status": "healthy"})

    async def post(self, url, json):
        self.calls.append((url, json))
        if url.endswith("/simulate"):
            return FakeResponse({"status": "completed", "mode": "replay", "metrics": {"aggregate": {"latency_ms": 2}}})
        if url.endswith("/v1/retrievaltool/json"):
            return FakeResponse({"result_count": 1, "sources": [{"id": "c1"}], "rag_profile": "quickstart", "retrieval_backend": "lexical_bm25"})
        if url.endswith("/synthesize"):
            return FakeResponse({"answer": "Grounded answer [C1].", "synthesis_backend": "deterministic", "llm_used": False, "citations": [{"citation_id": "C1"}]})
        return FakeResponse({})


class CaptureSimulationPayloadClient(FakeAsyncClient):
    last_simulation_payload = None

    async def post(self, url, json):
        if url.endswith("/simulate"):
            CaptureSimulationPayloadClient.last_simulation_payload = json
        return await super().post(url, json)


def _reload_agent_service(monkeypatch):
    for name in ["agent_service", "agent"]:
        sys.modules.pop(name, None)
    monkeypatch.setenv("SIMULATION_BASE_URL", "http://simulation:7000")
    monkeypatch.setenv("RAG_BASE_URL", "http://rag:7001")
    return importlib.import_module("agent_service")


def _reload_gateway(monkeypatch):
    for name in ["gateway", "agent"]:
        sys.modules.pop(name, None)
    monkeypatch.setenv("AGENT_BASE_URL", "http://agent:9090")
    return importlib.import_module("gateway")


def test_agent_health_endpoint_uses_mocked_dependencies(monkeypatch):
    service = _reload_agent_service(monkeypatch)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)

    body = asyncio.run(service.health_check(Response()))

    assert body["ready"] is True
    assert body["agent_profile"] == "quickstart"
    assert body["synthesis_backend"] == "deterministic"
    assert body["llm_used"] is False


def test_agent_canonical_request_reaches_mocked_simulation_and_rag(monkeypatch):
    service = _reload_agent_service(monkeypatch)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)

    request = service.ChatCompletionRequest(messages="Diagnose handover failure", thread_id="t1", stream=False)
    body = asyncio.run(service.chat_completions(request))

    assert body["status"] == "completed"
    assert body["evidence"]["simulation_reached"] is True
    assert body["evidence"]["rag_reached"] is True
    assert body["evidence"]["simulation_mode"] == "replay"
    assert body["evidence"]["synthesis_backend"] == "deterministic"
    assert body["evidence"]["llm_used"] is False


def test_agent_request_id_is_preserved_in_response(monkeypatch):
    service = _reload_agent_service(monkeypatch)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)

    request = service.ChatCompletionRequest(
        messages="Diagnose handover failure",
        thread_id="t1",
        request_id="gw-12345",
        stream=False,
    )
    body = asyncio.run(service.chat_completions(request))

    assert body["request_id"] == "gw-12345"
    assert body["evidence"]["request_id"] == "gw-12345"


def test_agent_explicit_fault_simulation_request_uses_fault_scenario(monkeypatch):
    service = _reload_agent_service(monkeypatch)
    monkeypatch.setattr(service.httpx, "AsyncClient", CaptureSimulationPayloadClient)

    request = service.ChatCompletionRequest(
        messages="Simulate handover_failure replay mode and provide fault KPIs.",
        thread_id="t1",
        stream=False,
    )
    asyncio.run(service.chat_completions(request))

    assert CaptureSimulationPayloadClient.last_simulation_payload["scenario"] == "handover_failure"


def test_agent_downstream_rag_failure_returns_non_success(monkeypatch):
    service = _reload_agent_service(monkeypatch)

    class RAGFailureClient(FakeAsyncClient):
        async def post(self, url, json):
            if url.endswith("/v1/retrievaltool/json"):
                return FakeResponse({"detail": "rag failed"}, status_code=503, text="rag failed")
            return await super().post(url, json)

    monkeypatch.setattr(service.httpx, "AsyncClient", RAGFailureClient)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.chat_completions(service.ChatCompletionRequest(messages="handover", stream=False)))
    assert exc.value.status_code == 502


def test_agent_downstream_simulation_failure_returns_non_success(monkeypatch):
    service = _reload_agent_service(monkeypatch)

    class SimulationFailureClient(FakeAsyncClient):
        async def post(self, url, json):
            if url.endswith("/simulate"):
                return FakeResponse({"detail": "simulation failed"}, status_code=503, text="simulation failed")
            return await super().post(url, json)

    monkeypatch.setattr(service.httpx, "AsyncClient", SimulationFailureClient)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.chat_completions(service.ChatCompletionRequest(messages="simulate", stream=False)))
    assert exc.value.status_code == 502


def test_agent_malformed_dependency_response_does_not_become_success(monkeypatch):
    service = _reload_agent_service(monkeypatch)

    class MalformedClient(FakeAsyncClient):
        async def post(self, url, json):
            if url.endswith("/v1/retrievaltool/json"):
                return FakeResponse(["not", "an", "object"])
            return await super().post(url, json)

    monkeypatch.setattr(service.httpx, "AsyncClient", MalformedClient)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.chat_completions(service.ChatCompletionRequest(messages="handover", stream=False)))
    assert exc.value.status_code == 502


def test_agent_defaults_do_not_claim_tailscale_live_or_llm(monkeypatch):
    service = _reload_agent_service(monkeypatch)

    assert "100." not in service.SIMULATION_BASE_URL
    assert "100." not in service.RAG_BASE_URL
    assert "Tailscale" not in (AGENT_ROOT / "agent_service.py").read_text(encoding="utf-8", errors="replace")
    assert service.SIMULATION_BASE_URL == "http://simulation:7000"
    assert service.RAG_BASE_URL == "http://rag:7001"


def test_intent_classifier_does_not_treat_mapping_as_health_check(monkeypatch):
    service = _reload_agent_service(monkeypatch)
    intent = service.classify_intent(
        "Map likely causes for handover-failure symptoms using scenario-mapping evidence and cite sources."
    )

    assert intent != service.IntentType.HEALTH_CHECK


def test_gateway_health_endpoint_uses_configured_agent(monkeypatch):
    gateway = _reload_gateway(monkeypatch)

    class GatewayClient(FakeAsyncClient):
        async def get(self, url):
            assert url == "http://agent:9090/v1/health_check"
            return FakeResponse({"ready": True}, status_code=200)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", GatewayClient)
    body = asyncio.run(gateway.health())

    assert body.agent_reachable is True


def test_gateway_nonstream_proxy_propagates_agent_failure(monkeypatch):
    gateway = _reload_gateway(monkeypatch)

    class FailingAgentClient(FakeAsyncClient):
        async def post(self, url, json):
            return FakeResponse({"detail": "agent failed"}, status_code=503, text="agent failed")

    monkeypatch.setattr(gateway.httpx, "AsyncClient", FailingAgentClient)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(gateway.chat(gateway.QueryRequest(query="handover", stream=False)))
    assert exc.value.status_code == 503


def test_gateway_malformed_agent_response_handling(monkeypatch):
    gateway = _reload_gateway(monkeypatch)

    class MalformedAgentClient(FakeAsyncClient):
        async def post(self, url, json):
            return FakeResponse(["not", "an", "object"])

    monkeypatch.setattr(gateway.httpx, "AsyncClient", MalformedAgentClient)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(gateway.chat(gateway.QueryRequest(query="handover", stream=False)))
    assert exc.value.status_code == 502


def test_gateway_includes_gateway_request_id_on_nonstream_response(monkeypatch):
    gateway = _reload_gateway(monkeypatch)
    monkeypatch.setattr(gateway.httpx, "AsyncClient", FakeAsyncClient)

    body = asyncio.run(gateway.chat(gateway.QueryRequest(query="handover", stream=False)))

    assert body["gateway_request_id"].startswith("gw-")


def test_gateway_timeout_handling(monkeypatch):
    gateway = _reload_gateway(monkeypatch)

    class TimeoutAgentClient(FakeAsyncClient):
        async def post(self, url, json):
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(gateway.httpx, "AsyncClient", TimeoutAgentClient)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(gateway.chat(gateway.QueryRequest(query="handover", stream=False)))
    assert exc.value.status_code == 504


def test_gateway_has_no_localhost_container_dns_confusion_or_tailscale_default(monkeypatch):
    gateway = _reload_gateway(monkeypatch)
    text = (AGENT_ROOT / "gateway.py").read_text(encoding="utf-8", errors="replace")

    assert gateway.AGENT_ENDPOINT == "http://agent:9090"
    assert "host.docker.internal" not in text
    assert "Tailscale" not in text
    assert "100." not in text
