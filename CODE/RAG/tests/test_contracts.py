import importlib
import json
import sys
import types
from pathlib import Path

RAG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAG_ROOT))

if importlib.util.find_spec("chromadb") is None:
    chromadb_stub = types.ModuleType("chromadb")
    chromadb_stub.PersistentClient = object
    sys.modules["chromadb"] = chromadb_stub

from app.schemas import (  # noqa: E402
    RetrievalRequest,
    SourceChunk,
    SynthesisCitation,
    SynthesisRequest,
    SynthesisResponse,
)
from app import config  # noqa: E402
from app import synthesis  # noqa: E402
from app import vector_store  # noqa: E402
from app.vector_store import TelcoVectorStore  # noqa: E402


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


class FakeEncoded:
    def __init__(self, vectors: list[list[float]]):
        self.vectors = vectors

    def tolist(self):
        return self.vectors


class FakeEmbeddingModel:
    def __init__(self):
        self.calls = []

    def encode(self, texts, normalize_embeddings, batch_size, show_progress_bar):
        self.calls.append(
            {
                "texts": texts,
                "normalize_embeddings": normalize_embeddings,
                "batch_size": batch_size,
                "show_progress_bar": show_progress_bar,
            }
        )
        return FakeEncoded([[0.1, 0.2, 0.3] for _ in texts])


class FakeReranker:
    def predict(self, pairs):
        return [0.2, 0.9][: len(pairs)]


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


def test_embedding_and_reranker_config_defaults_are_local(monkeypatch):
    with monkeypatch.context() as env:
        for name in [
            "EMBEDDING_BACKEND",
            "EMBEDDING_ENDPOINT_URL",
            "EMBEDDING_MODEL",
            "EMBEDDING_TIMEOUT_SECONDS",
            "RERANKER_BACKEND",
            "RERANKER_ENDPOINT_URL",
            "RERANKER_MODEL",
            "RERANKER_TIMEOUT_SECONDS",
        ]:
            env.delenv(name, raising=False)

        reloaded = importlib.reload(config)

        assert reloaded.EMBEDDING_BACKEND == "local"
        assert reloaded.EMBEDDING_ENDPOINT_URL == ""
        assert reloaded.EMBEDDING_MODEL == "BAAI/bge-base-en-v1.5"
        assert reloaded.EMBEDDING_TIMEOUT_SECONDS == 30
        assert reloaded.RERANKER_BACKEND == "local"
        assert reloaded.RERANKER_ENDPOINT_URL == ""
        assert reloaded.RERANKER_MODEL == "BAAI/bge-reranker-base"
        assert reloaded.RERANKER_TIMEOUT_SECONDS == 30

    importlib.reload(config)


def test_external_embedding_and_reranker_config_can_be_parsed(monkeypatch):
    with monkeypatch.context() as env:
        env.setenv("EMBEDDING_BACKEND", "external")
        env.setenv("EMBEDDING_ENDPOINT_URL", "http://embedding.example/embed")
        env.setenv("EMBEDDING_MODEL", "opea-embedding")
        env.setenv("EMBEDDING_TIMEOUT_SECONDS", "9")
        env.setenv("RERANKER_BACKEND", "external")
        env.setenv("RERANKER_ENDPOINT_URL", "http://reranker.example/rerank")
        env.setenv("RERANKER_MODEL", "opea-reranker")
        env.setenv("RERANKER_TIMEOUT_SECONDS", "11")

        reloaded = importlib.reload(config)

        assert reloaded.EMBEDDING_BACKEND == "external"
        assert reloaded.EMBEDDING_ENDPOINT_URL == "http://embedding.example/embed"
        assert reloaded.EMBEDDING_MODEL == "opea-embedding"
        assert reloaded.EMBEDDING_TIMEOUT_SECONDS == 9
        assert reloaded.RERANKER_BACKEND == "external"
        assert reloaded.RERANKER_ENDPOINT_URL == "http://reranker.example/rerank"
        assert reloaded.RERANKER_MODEL == "opea-reranker"
        assert reloaded.RERANKER_TIMEOUT_SECONDS == 11

    importlib.reload(config)


def test_external_embedding_failure_falls_back_to_local_model(monkeypatch):
    store = object.__new__(TelcoVectorStore)
    store.embedding_model = FakeEmbeddingModel()

    def fake_urlopen(request, timeout):
        raise TimeoutError("embedding endpoint timed out")

    monkeypatch.setattr(config, "EMBEDDING_BACKEND", "external")
    monkeypatch.setattr(config, "EMBEDDING_ENDPOINT_URL", "http://embedding.example/embed")
    monkeypatch.setattr(config, "EMBEDDING_TIMEOUT_SECONDS", 3)
    monkeypatch.setattr(vector_store.urllib.request, "urlopen", fake_urlopen)

    embeddings = store._encode_texts(["handover failure"])

    assert embeddings == [[0.1, 0.2, 0.3]]
    assert store.embedding_model.calls[0]["texts"] == ["handover failure"]
    assert store.embedding_model.calls[0]["normalize_embeddings"] is True


def test_external_reranker_failure_falls_back_to_local_model(monkeypatch):
    store = object.__new__(TelcoVectorStore)
    store.reranker = FakeReranker()
    candidates = [{"text": "first"}, {"text": "second"}]

    def fake_urlopen(request, timeout):
        raise TimeoutError("reranker endpoint timed out")

    monkeypatch.setattr(config, "RERANKER_BACKEND", "external")
    monkeypatch.setattr(config, "RERANKER_ENDPOINT_URL", "http://reranker.example/rerank")
    monkeypatch.setattr(config, "RERANKER_TIMEOUT_SECONDS", 3)
    monkeypatch.setattr(vector_store.urllib.request, "urlopen", fake_urlopen)

    assert store._rerank_scores("query", candidates) == [0.2, 0.9]


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
    assert len(queries) >= 10

    intents = {entry["intent_type"] for entry in queries}
    joined_queries = " ".join(
        f"{entry['query']} {entry.get('notes', '')} {entry.get('expected_evidence_type', '')}".lower()
        for entry in queries
    )

    assert {"GENERAL_QNA", "DIAGNOSTIC", "OPTIMIZATION"}.issubset(intents)
    assert "handover" in joined_queries
    assert "energy" in joined_queries
    assert "interference" in joined_queries
    assert "ng-ran" in joined_queries or "ng ran" in joined_queries
    assert "o-ran" in joined_queries or "oran" in joined_queries
    assert "kpi" in joined_queries or "simulation" in joined_queries

    for entry in queries:
        assert REQUIRED_QUERY_FIELDS.issubset(entry)
        assert entry["intent_type"] in ALLOWED_INTENTS
        assert entry["expected_evidence_type"] in ALLOWED_EVIDENCE_TYPES
        assert entry["query"].strip()
        assert entry["notes"].strip()
