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


DEMO_QUERY_PATH = RAG_ROOT / "eval" / "rag_demo_queries.json"
REQUIRED_QUERY_FIELDS = {"intent_type", "query", "expected_evidence_type", "notes"}
ALLOWED_INTENTS = {"GENERAL_QNA", "DIAGNOSTIC", "OPTIMIZATION"}
ALLOWED_EVIDENCE_TYPES = {"runbook", "scenario", "spec", "mixed"}


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
