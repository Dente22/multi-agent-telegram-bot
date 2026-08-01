"""RAG-related Pydantic schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceCitation(BaseModel):
    """Exact source citation returned with RAG answers."""

    document_id: str
    chunk_id: str
    filename: str
    excerpt: str = Field(..., max_length=500)
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    page: int | None = None


class RAGAnswer(BaseModel):
    """Grounded RAG response with citations."""

    model_config = {"extra": "forbid"}

    answer: str
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    sources: list[SourceCitation] = Field(default_factory=list)
