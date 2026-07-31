import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


RAG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAG_ROOT))


def _load_service(monkeypatch, profile="quickstart", full_index_path=None):
    monkeypatch.setenv("RAG_PROFILE", profile)
    if full_index_path:
        monkeypatch.setenv("RAG_FULL_INDEX_PATH", str(full_index_path))
    config = importlib.import_module("app.config")
    importlib.reload(config)
    sys.modules.pop("app.rag_service", None)
    return importlib.import_module("app.rag_service")


def test_health_is_liveness_only(monkeypatch):
    service = _load_service(monkeypatch)
    response = TestClient(service.app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert "chunks" not in body
    assert body["rag_profile"] == "quickstart"


def test_ready_reports_valid_quickstart(monkeypatch):
    service = _load_service(monkeypatch)
    response = TestClient(service.app).get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["retrieval_backend"] == "lexical_bm25"
    assert body["chunk_count"] > 0


def test_capabilities_identifies_profile_backend_and_synthesis(monkeypatch):
    service = _load_service(monkeypatch)
    response = TestClient(service.app).get("/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["active_profile"] == "quickstart"
    assert body["active_retrieval_backend"] == "lexical_bm25"
    assert body["deterministic_synthesis"] is True


def test_structured_retrieval_response_identifies_quickstart_backend(monkeypatch):
    service = _load_service(monkeypatch)
    response = TestClient(service.app).post(
        "/v1/retrievaltool/json",
        json={"text": "handover failure neighbor relation SINR", "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rag_profile"] == "quickstart"
    assert body["retrieval_backend"] == "lexical_bm25"
    assert body["result_count"] == len(body["sources"])
    assert body["fallback_used"] is False
    assert body["raw"]["score_type"] == "bm25_raw"
    assert "confidence" not in body["raw"]
    assert body["sources"][0]["score_type"] == "bm25_raw"


def test_empty_retrieval_is_not_service_failure(monkeypatch):
    service = _load_service(monkeypatch)
    response = TestClient(service.app).post(
        "/v1/retrievaltool/json",
        json={"text": "xylophone marmalade asteroid", "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == []
    assert body["result_count"] == 0
    assert body["warnings"]


def test_text_compatibility_endpoint_still_returns_text(monkeypatch):
    service = _load_service(monkeypatch)
    response = TestClient(service.app).post(
        "/v1/retrievaltool",
        json={"text": "energy optimization KPI guardrails"},
    )

    assert response.status_code == 200
    assert "Energy Optimization" in response.text


def test_synthesize_deterministic_labels_llm_used_false(monkeypatch):
    service = _load_service(monkeypatch)
    response = TestClient(service.app).post(
        "/synthesize",
        json={"query": "Why might handover failures occur?", "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["synthesis_backend"] == "deterministic"
    assert body["llm_used"] is False
    assert body["citations"]


def test_unavailable_full_profile_never_falls_back_to_quickstart(monkeypatch, tmp_path):
    missing_index = tmp_path / "missing-chroma"
    service = _load_service(monkeypatch, profile="full", full_index_path=missing_index)
    client = TestClient(service.app)

    ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json()["rag_profile"] == "full"

    retrieval = client.post("/v1/retrievaltool/json", json={"text": "handover failure"})
    assert retrieval.status_code == 503
    assert "Quickstart" not in retrieval.text
    assert "quickstart" not in retrieval.text
