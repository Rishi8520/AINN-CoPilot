import importlib
import json
import sys
from pathlib import Path

import pytest


RAG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAG_ROOT))

from app.lexical_retriever import LexicalBM25Retriever, tokenize  # noqa: E402
from app.quickstart_corpus import CorpusValidationError, load_quickstart_corpus  # noqa: E402


def reload_config(monkeypatch, **env):
    for key in [
        "RAG_PROFILE",
        "RAG_QUICKSTART_CORPUS_PATH",
        "RAG_QUICKSTART_TOP_K",
        "RAG_FULL_INDEX_PATH",
        "RAG_AUTO_INGEST",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    module = importlib.import_module("app.config")
    return importlib.reload(module)


def test_default_profile_is_quickstart(monkeypatch):
    config = reload_config(monkeypatch)

    assert config.RAG_PROFILE == "quickstart"
    assert config.RAG_AUTO_INGEST is False


def test_full_profile_is_accepted(monkeypatch):
    config = reload_config(monkeypatch, RAG_PROFILE="full")

    assert config.RAG_PROFILE == "full"


def test_invalid_profile_is_rejected(monkeypatch):
    with pytest.raises(ValueError):
        reload_config(monkeypatch, RAG_PROFILE="semantic")


def test_empty_profile_becomes_quickstart(monkeypatch):
    config = reload_config(monkeypatch, RAG_PROFILE="  ")

    assert config.RAG_PROFILE == "quickstart"


def test_relative_corpus_path_resolves_from_rag_root(monkeypatch):
    config = reload_config(monkeypatch, RAG_QUICKSTART_CORPUS_PATH="quickstart/corpus.jsonl")

    assert config.RAG_QUICKSTART_CORPUS_PATH == (RAG_ROOT / "quickstart" / "corpus.jsonl").resolve()


def test_quickstart_corpus_and_manifest_validate():
    corpus = load_quickstart_corpus()

    assert corpus.corpus_id == "telcomind-rag-quickstart"
    assert len(corpus.chunks) == corpus.manifest["chunk_count"]
    for chunk in corpus.chunks:
        assert not Path(chunk.metadata["source"]).is_absolute()
        assert chunk.metadata["source_type"] in {"runbook", "scenario", "spec"}
        assert "source" in chunk.metadata
        assert "title" in chunk.metadata
        assert "section" in chunk.metadata


def test_path_traversal_is_rejected():
    with pytest.raises(CorpusValidationError):
        load_quickstart_corpus(RAG_ROOT / ".." / "outside.jsonl")


def test_lexical_retrieval_is_deterministic_and_genuine():
    retriever = LexicalBM25Retriever()
    first = retriever.search("handover failure neighbor relation SINR", top_k=5)
    second = retriever.search("handover failure neighbor relation SINR", top_k=5)

    assert [item["id"] for item in first] == [item["id"] for item in second]
    assert first
    assert any("handover" in item["text"].lower() for item in first[:2])
    assert first[0]["score"] > 0
    assert first[0]["score_type"] == "bm25_raw"
    assert "confidence" not in first[0]


def test_top_k_bounds_and_acronym_normalization():
    retriever = LexicalBM25Retriever(top_k=50)

    assert len(retriever.search("O-RAN NG-RAN KPI SINR", top_k=100)) <= 20
    tokens = set(tokenize("O-RAN NG-RAN KPI SINR"))
    assert {"o-ran", "oran", "ng-ran", "ngran", "kpi", "sinr"}.issubset(tokens)


def test_expected_demo_queries_retrieve_evidence():
    retriever = LexicalBM25Retriever()
    queries = json.loads((RAG_ROOT / "quickstart" / "demo_queries.json").read_text(encoding="utf-8"))

    for entry in queries:
        results = retriever.search(entry["query"], top_k=5)
        returned_ids = [item["id"] for item in results]
        expected = entry["expected_chunk_ids"]
        if expected:
            assert any(chunk_id in returned_ids for chunk_id in expected), entry["query"]
        else:
            assert all(item["score"] >= 0 for item in results)


def test_no_match_query_is_honest_empty():
    retriever = LexicalBM25Retriever()

    assert retriever.search("xylophone marmalade asteroid", top_k=5) == []


def test_definition_retrieves_overview_and_baseline_retrieves_measurement_guidance():
    retriever = LexicalBM25Retriever()
    definition = retriever.search("what is O-RAN", top_k=4)
    assert "overview" in definition[0]["metadata"]["section"].lower()
    assert any("Open RAN" in row["text"] for row in definition)
    security = retriever.search("Explain O-RAN security architecture", top_k=4)
    assert any("security" in row["metadata"]["section"].lower() for row in security)
    baseline = retriever.search("Run a baseline simulation with 100 UEs and analyze throughput and latency", top_k=4)
    assert any("baseline_measurement_runbook" in row["metadata"]["source"] for row in baseline)


def test_quickstart_import_does_not_load_heavy_modules(monkeypatch):
    for module_name in ["chromadb", "sentence_transformers", "torch"]:
        sys.modules.pop(module_name, None)

    retriever = LexicalBM25Retriever()

    assert retriever.count() > 0
    assert "chromadb" not in sys.modules
    assert "sentence_transformers" not in sys.modules
    assert "torch" not in sys.modules
