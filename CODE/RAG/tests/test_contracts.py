import json
import sys
from pathlib import Path

RAG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAG_ROOT))

from app.schemas import (  # noqa: E402
    RetrievalRequest,
    SourceChunk,
    SynthesisCitation,
    SynthesisRequest,
    SynthesisResponse,
)
from app import config  # noqa: E402
from app import synthesis  # noqa: E402


DEMO_QUERY_PATH = RAG_ROOT / "eval" / "rag_demo_queries.json"
REQUIRED_QUERY_FIELDS = {"intent_type", "query", "expected_evidence_type", "notes"}
ALLOWED_INTENTS = {"GENERAL_QNA", "DIAGNOSTIC", "OPTIMIZATION"}
ALLOWED_EVIDENCE_TYPES = {"runbook", "scenario", "spec", "mixed"}


class FakeLLMResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _sample_sources() -> list[SourceChunk]:
    return [
        SourceChunk(
            id="handover-runbook-1",
            source="knowledge_base/runbooks/handover.md",
            title="Handover Failure Runbook",
            section="Initial checks",
            score=0.91,
            text=(
                "Handover failures can be caused by weak radio conditions, missing neighbor "
                "relations, and mobility parameter changes."
            ),
            source_type="runbook",
            chunk=1,
        )
    ]


def test_retrieval_request_effective_query_supports_text_and_query():
    assert RetrievalRequest(text="  handover failure  ").effective_query() == "handover failure"
    assert RetrievalRequest(query="  energy optimization  ").effective_query() == "energy optimization"


def test_source_chunk_accepts_citation_metadata_fields():
    chunk = SourceChunk(
        id="handover-runbook-1",
        source="knowledge_base/runbooks/handover.md",
        title="Handover Failure Runbook",
        section="Initial checks",
        score=0.83,
        text="Check neighbor relations and recent mobility parameter changes.",
        kind="runbook",
        source_type="runbook",
        chunk=2,
        page=7,
    )

    assert chunk.kind == "runbook"
    assert chunk.source_type == "runbook"
    assert chunk.chunk == 2
    assert chunk.page == 7


def test_synthesis_request_accepts_simulation_kpis_and_intent_type():
    request = SynthesisRequest(
        query="Why did handover failures increase?",
        simulation_kpis={"handover_success_rate": 91.4, "latency_ms": 28},
        intent_type="DIAGNOSTIC",
    )

    assert request.simulation_kpis == {"handover_success_rate": 91.4, "latency_ms": 28}
    assert request.intent_type == "DIAGNOSTIC"


def test_synthesis_response_includes_intent_type_and_retrieval_context_count():
    response = SynthesisResponse(
        query="How is the cell performing?",
        answer="The cell appears close to baseline.",
        confidence="medium",
        citations=[
            SynthesisCitation(
                source="knowledge_base/scenarios/baseline.md",
                title="Baseline Scenario",
                section="Normal operation",
                score=0.74,
                source_type="scenario",
            )
        ],
        assumptions=["Retrieved evidence reflects the current indexed knowledge base."],
        recommended_action="Continue monitoring and compare against the next KPI window.",
        used_simulation_kpis={"latency_ms": 18},
        intent_type="GENERAL_QNA",
        retrieval_context_count=1,
    )

    assert response.intent_type == "GENERAL_QNA"
    assert response.retrieval_context_count == 1


def test_synthesis_default_llm_disabled_uses_deterministic_path(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM endpoint should not be called when disabled.")

    monkeypatch.setattr(config, "LLM_ENABLED", False)
    monkeypatch.setattr(config, "LLM_ENDPOINT_URL", "http://llm.example")
    monkeypatch.setattr(synthesis.urllib.request, "urlopen", fail_if_called)

    response = synthesis.synthesize_response(
        query="Why might handover failures occur?",
        sources=_sample_sources(),
    )

    assert response.answer.startswith("Based on the retrieved context")
    assert response.citations[0].title == "Handover Failure Runbook"


def test_synthesis_llm_success_replaces_answer_and_preserves_contract(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeLLMResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Handover failures may occur when radio conditions are weak or "
                                "neighbor relations are missing [1]."
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(config, "LLM_ENDPOINT_URL", "http://llm.example")
    monkeypatch.setattr(config, "LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
    monkeypatch.setattr(config, "LLM_TIMEOUT_SECONDS", 7)
    monkeypatch.setattr(synthesis.urllib.request, "urlopen", fake_urlopen)

    response = synthesis.synthesize_response(
        query="Why might handover failures occur?",
        sources=_sample_sources(),
        simulation_kpis={"handover_success_rate": 0.72},
        intent_type="DIAGNOSTIC",
    )

    assert response.answer == (
        "Handover failures may occur when radio conditions are weak or neighbor relations are missing [1]."
    )
    assert response.citations[0].title == "Handover Failure Runbook"
    assert response.used_simulation_kpis == {"handover_success_rate": 0.72}
    assert response.intent_type == "DIAGNOSTIC"
    assert response.retrieval_context_count == 1
    assert captured["url"] == "http://llm.example/v1/chat/completions"
    assert captured["timeout"] == 7
    assert captured["payload"]["model"] == "Qwen/Qwen2.5-0.5B-Instruct"
    assert "[1]" in captured["payload"]["messages"][1]["content"]
    assert "do not invent 3gpp or o-ran clause numbers" in captured["payload"]["messages"][0][
        "content"
    ].lower()


def test_synthesis_llm_failure_falls_back_deterministically(monkeypatch):
    def fake_urlopen(request, timeout):
        raise TimeoutError("vLLM timed out")

    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(config, "LLM_ENDPOINT_URL", "http://llm.example")
    monkeypatch.setattr(synthesis.urllib.request, "urlopen", fake_urlopen)

    response = synthesis.synthesize_response(
        query="Why might handover failures occur?",
        sources=_sample_sources(),
    )

    assert response.answer.startswith("Based on the retrieved context")
    assert "deterministic fallback synthesis was used" in response.assumptions[-1]


def test_demo_query_json_exists_parses_and_has_required_fields():
    queries = json.loads(DEMO_QUERY_PATH.read_text(encoding="utf-8"))

    assert isinstance(queries, list)
    assert len(queries) >= 8

    intents = {entry["intent_type"] for entry in queries}
    joined_queries = " ".join(entry["query"].lower() for entry in queries)

    assert {"GENERAL_QNA", "DIAGNOSTIC", "OPTIMIZATION"}.issubset(intents)
    assert "handover" in joined_queries
    assert "energy" in joined_queries
    assert "interference" in joined_queries
    assert "baseline" in joined_queries or "normal operation" in joined_queries

    for entry in queries:
        assert REQUIRED_QUERY_FIELDS.issubset(entry)
        assert entry["intent_type"] in ALLOWED_INTENTS
        assert entry["expected_evidence_type"] in ALLOWED_EVIDENCE_TYPES
        assert entry["query"].strip()
        assert entry["notes"].strip()
