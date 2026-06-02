from typing import Any, Optional
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


class RetrievalResponse(BaseModel):
    query: str
    answer_context: str
    sources: list[SourceChunk]
    raw: dict[str, Any] = {}


class IngestResponse(BaseModel):
    status: str
    documents_indexed: int
    chunks_indexed: int
    collection: str
