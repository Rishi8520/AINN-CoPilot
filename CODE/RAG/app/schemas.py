from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class RetrievalRequest(BaseModel):
    text: Optional[str] = Field(default=None, description="OPEA retrievaltool-compatible query field.")
    query: Optional[str] = Field(default=None, description="Plain retrieval query field.")
    top_k: Optional[int] = Field(default=None, ge=1, le=20)

    def effective_query(self) -> str:
        value = self.text or self.query or ""
        return value.strip()


class SourceChunk(BaseModel):
    id: str
    source: str
    title: str
    section: str
    score: float
    text: str
    kind: Optional[str] = None
    source_type: Optional[str] = None
    chunk: Optional[int] = None
    page: Optional[int] = None
    score_type: Optional[str] = None
    retrieval_backend: Optional[str] = None
    corpus_profile: Optional[str] = None
    corpus_id: Optional[str] = None


class SynthesisCitation(BaseModel):
    citation_id: Optional[str] = None
    source: str
    title: str
    section: str
    chunk: Optional[int] = None
    page: Optional[int] = None
    kind: Optional[str] = None
    source_type: Optional[str] = None
    score: float


class SynthesisRequest(BaseModel):
    query: str
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    contexts: Optional[list[SourceChunk]] = None
    simulation_kpis: Optional[dict[str, Any]] = None
    simulation_context: Optional[dict[str, Any]] = None
    intent_type: Optional[str] = None


class SynthesisResponse(BaseModel):
    query: str
    answer: str
    confidence: Literal["high", "medium", "low"]
    citations: list[SynthesisCitation]
    assumptions: list[str]
    recommended_action: str
    used_simulation_kpis: Optional[dict[str, Any]] = None
    intent_type: Optional[str] = None
    retrieval_context_count: int
    requested_backend: str = "deterministic"
    synthesis_backend: str = "deterministic"
    llm_used: bool = False
    fallback_used: bool = False
    attempted_provider: Optional[str] = None
    configured_provider: Optional[str] = None
    configured_model: Optional[str] = None
    response_model: Optional[str] = None
    fallback_reason: Optional[str] = None
    error_category: Optional[str] = None
    citation_validation: Literal["passed", "warned", "failed"] = "passed"
    unknown_citation_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RetrievalResponse(BaseModel):
    query: str
    answer_context: str
    sources: list[SourceChunk]
    raw: dict[str, Any] = Field(default_factory=dict)
    rag_profile: str = "quickstart"
    retrieval_backend: str = "lexical_bm25"
    corpus_id: Optional[str] = None
    index_id: Optional[str] = None
    result_count: int = 0
    fallback_used: bool = False
    warnings: list[str] = Field(default_factory=list)


class IngestResponse(BaseModel):
    status: str
    documents_indexed: int
    chunks_indexed: int
    collection: str
