from fastapi import FastAPI, HTTPException
from app import config
from app.loaders import load_knowledge_base
from app.schemas import IngestResponse, RetrievalRequest, RetrievalResponse, SourceChunk
from app.vector_store import TelcoVectorStore

app = FastAPI(
    title="TelcoMind Member 2 RAG Service",
    description="3GPP/O-RAN retrieval service with OPEA retrievaltool-compatible endpoint.",
    version="1.0.0",
)

store = TelcoVectorStore()


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "collection": config.COLLECTION_NAME,
        "chunks": store.count(),
        "embedding_model": config.EMBEDDING_MODEL,
        "reranker_model": config.RERANKER_MODEL,
    }


@app.post("/ingest", response_model=IngestResponse)
async def ingest():
    chunks = load_knowledge_base(config.KNOWLEDGE_BASE_DIR)
    indexed = store.ingest(chunks)
    return IngestResponse(
        status="success",
        documents_indexed=len({c.metadata.get("source") for c in chunks}),
        chunks_indexed=indexed,
        collection=config.COLLECTION_NAME,
    )


def _format_context(query: str, items: list[dict]) -> RetrievalResponse:
    sources = [
        SourceChunk(
            id=item["id"],
            source=item["metadata"].get("source", "unknown"),
            title=item["metadata"].get("title", "Untitled"),
            section=item["metadata"].get("section", "unknown"),
            score=round(float(item["score"]), 4),
            text=item["text"],
        )
        for item in items
    ]

    blocks = []
    for index, source in enumerate(sources, start=1):
        blocks.append(
            f"[{index}] {source.title} ({source.section})\n"
            f"Source: {source.source}\n"
            f"Relevance: {source.score}\n"
            f"{source.text}"
        )

    return RetrievalResponse(
        query=query,
        answer_context="\n\n".join(blocks),
        sources=sources,
        raw={"result_count": len(sources)},
    )


@app.post("/retrieve", response_model=RetrievalResponse)
async def retrieve(req: RetrievalRequest):
    query = req.effective_query()
    if not query:
        raise HTTPException(status_code=400, detail="Missing query/text")
    return _format_context(query, store.search(query, req.top_k))


@app.post("/v1/retrievaltool")
async def opea_retrievaltool(req: RetrievalRequest):
    query = req.effective_query()
    if not query:
        raise HTTPException(status_code=400, detail="Missing text")
    response = _format_context(query, store.search(query, req.top_k))
    return response.answer_context
