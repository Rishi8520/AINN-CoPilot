from fastapi import FastAPI, HTTPException, Response
from app import config
from app.loaders import load_knowledge_base
from app.lexical_retriever import LexicalBM25Retriever
from app.quickstart_corpus import CorpusValidationError, load_quickstart_corpus
from app.schemas import (
    IngestResponse,
    RetrievalRequest,
    RetrievalResponse,
    SourceChunk,
    SynthesisRequest,
    SynthesisResponse,
)
from app.synthesis import SynthesisFailure, synthesize_response, synthesis_readiness
from app.vector_store import FullRAGUnavailable, TelcoVectorIngestStore, TelcoVectorStore, full_readiness

app = FastAPI(
    title="TelcoMind Member 2 RAG Service",
    description="3GPP/O-RAN retrieval service with OPEA retrievaltool-compatible endpoint.",
    version="1.0.0",
)

_store = None
_store_error = ""

HEALTH_PATH = "/health"
RETRIEVE_PATH = "/v1/retrievaltool/json"
RETRIEVE_TEXT_COMPAT_PATH = "/v1/retrievaltool"
SYNTHESIZE_PATH = "/synthesize"
READY_PATH = "/ready"
CAPABILITIES_PATH = "/capabilities"
INGEST_PATH = "/ingest"


def _backend_id() -> str:
    return "lexical_bm25" if config.RAG_PROFILE == "quickstart" else "chroma_bge_reranker"


def _get_store():
    global _store, _store_error
    if _store is not None:
        return _store
    try:
        if config.RAG_PROFILE == "quickstart":
            _store = LexicalBM25Retriever()
        else:
            _store = TelcoVectorStore()
        _store_error = ""
        return _store
    except (CorpusValidationError, FullRAGUnavailable, ValueError) as exc:
        _store_error = str(exc)
        raise HTTPException(status_code=503, detail=_store_error) from exc


def _quickstart_readiness() -> dict:
    try:
        corpus = load_quickstart_corpus()
        return {
            "rag_profile": "quickstart",
            "retrieval_backend": "lexical_bm25",
            "ready": True,
            "corpus_valid": True,
            "corpus_id": corpus.corpus_id,
            "corpus_version": corpus.version,
            "chunk_count": len(corpus.chunks),
            "warnings": [],
        }
    except CorpusValidationError as exc:
        return {
            "rag_profile": "quickstart",
            "retrieval_backend": "lexical_bm25",
            "ready": False,
            "corpus_valid": False,
            "warnings": [str(exc)],
        }


@app.get(HEALTH_PATH)
async def health():
    return {
        "status": "healthy",
        "rag_profile": config.RAG_PROFILE,
        "retrieval_backend": _backend_id(),
        "readiness_path": READY_PATH,
    }


@app.get(READY_PATH)
async def ready(response: Response):
    details = _quickstart_readiness() if config.RAG_PROFILE == "quickstart" else full_readiness()
    synthesis = synthesis_readiness()
    details["synthesis"] = synthesis
    details["warnings"] = [*details.get("warnings", []), *synthesis.get("warnings", [])]
    if synthesis.get("degraded") and details.get("ready"):
        details["degraded"] = True
    if not details.get("ready"):
        response.status_code = 503
    if not synthesis.get("ready"):
        details["ready"] = False
        response.status_code = 503
    return details


@app.get(CAPABILITIES_PATH)
async def capabilities():
    return {
        "active_profile": config.RAG_PROFILE,
        "supported_profiles": ["quickstart", "full"],
        "active_retrieval_backend": _backend_id(),
        "backends": {
            "quickstart": "lexical_bm25",
            "full": "chroma_bge_reranker",
        },
        "deterministic_synthesis": True,
        "supported_synthesis_backends": ["deterministic", "openai_compatible"],
        "configured_synthesis_backend": config.RAG_SYNTHESIS_BACKEND,
        "openai_compatible": {
            "configured": bool(config.LLM_BASE_URL and config.LLM_MODEL),
            "provider": config.LLM_PROVIDER,
            "model_configured": bool(config.LLM_MODEL),
            "api_key_configured": bool(config.LLM_API_KEY),
            "llm_required": config.LLM_REQUIRED,
            "fallback_allowed": config.LLM_FALLBACK_TO_DETERMINISTIC,
            "endpoint_reachability": "not_checked",
        },
        "vllm_configured": bool(config.LLM_PROVIDER == "vllm" and config.LLM_BASE_URL and config.LLM_MODEL),
        "auto_ingest": config.RAG_AUTO_INGEST,
        "warnings": [
            "Full semantic mode is explicit and never receives quickstart fallback.",
            "Capabilities do not claim OpenAI-compatible endpoint reachability based only on URL presence.",
        ],
    }


@app.post(INGEST_PATH, response_model=IngestResponse)
async def ingest():
    if config.RAG_PROFILE != "full":
        raise HTTPException(
            status_code=409,
            detail="Ingestion is available only with RAG_PROFILE=full and must be invoked explicitly.",
        )
    chunks = load_knowledge_base(config.KNOWLEDGE_BASE_DIR)
    indexed = TelcoVectorIngestStore().ingest(chunks)
    return IngestResponse(
        status="success",
        documents_indexed=len({c.metadata.get("source") for c in chunks}),
        chunks_indexed=indexed,
        collection=config.COLLECTION_NAME,
    )


def _format_context(query: str, items: list[dict], store) -> RetrievalResponse:
    sources = [
        SourceChunk(
            id=item["id"],
            source=item["metadata"].get("source", "unknown"),
            title=item["metadata"].get("title", "Untitled"),
            section=item["metadata"].get("section", "unknown"),
            score=round(float(item["score"]), 4),
            text=item["text"],
            kind=item["metadata"].get("kind"),
            source_type=item["metadata"].get("source_type"),
            chunk=item["metadata"].get("chunk"),
            page=item["metadata"].get("page"),
            score_type=item.get("score_type") or item["metadata"].get("score_type"),
            retrieval_backend=item["metadata"].get("retrieval_backend") or _backend_id(),
            corpus_profile=item["metadata"].get("corpus_profile") or config.RAG_PROFILE,
            corpus_id=item["metadata"].get("corpus_id"),
        )
        for item in items
    ]

    blocks = []
    for index, source in enumerate(sources, start=1):
        blocks.append(
            f"[{index}] {source.title} ({source.section})\n"
            f"Source: {source.source}\n"
            f"Ranking score ({source.score_type or 'raw'}): {source.score}\n"
            f"{source.text}"
        )

    capabilities = store.capabilities() if hasattr(store, "capabilities") else {}
    corpus_id = capabilities.get("corpus_id")
    index_id = config.COLLECTION_NAME if config.RAG_PROFILE == "full" else None
    warnings = [] if sources else [f"No matching {config.RAG_PROFILE} corpus/index chunks were found for the query."]
    return RetrievalResponse(
        query=query,
        answer_context="\n\n".join(blocks),
        sources=sources,
        raw={
            "result_count": len(sources),
            "rag_profile": config.RAG_PROFILE,
            "retrieval_backend": _backend_id(),
            "score_type": sources[0].score_type if sources else None,
            "fallback_used": False,
        },
        rag_profile=config.RAG_PROFILE,
        retrieval_backend=_backend_id(),
        corpus_id=corpus_id,
        index_id=index_id,
        result_count=len(sources),
        fallback_used=False,
        warnings=warnings,
    )


@app.post("/retrieve", response_model=RetrievalResponse)
async def retrieve(req: RetrievalRequest):
    query = req.effective_query()
    if not query:
        raise HTTPException(status_code=400, detail="Missing query/text")
    store = _get_store()
    return _format_context(query, store.search(query, req.top_k), store)


@app.post(SYNTHESIZE_PATH, response_model=SynthesisResponse)
async def synthesize(req: SynthesisRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Missing query")

    if req.contexts is not None:
        sources = req.contexts
    else:
        store = _get_store()
        sources = _format_context(query, store.search(query, req.top_k), store).sources

    try:
        return synthesize_response(
            query=query,
            sources=sources,
            simulation_kpis=req.simulation_kpis,
            intent_type=req.intent_type,
        )
    except SynthesisFailure as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post(RETRIEVE_TEXT_COMPAT_PATH)
async def opea_retrievaltool(req: RetrievalRequest):
    query = req.effective_query()
    if not query:
        raise HTTPException(status_code=400, detail="Missing text")
    store = _get_store()
    response = _format_context(query, store.search(query, req.top_k), store)
    return response.answer_context


@app.post(RETRIEVE_PATH, response_model=RetrievalResponse)
async def opea_retrievaltool_json(req: RetrievalRequest):
    query = req.effective_query()
    if not query:
        raise HTTPException(status_code=400, detail="Missing text")
    store = _get_store()
    return _format_context(query, store.search(query, req.top_k), store)
