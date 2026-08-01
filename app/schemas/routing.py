"""Router decision schema for multi-agent dispatch."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class AgentKind(str, Enum):
    """Available specialist agents."""

    RAG = "rag"
    EXTRACTOR = "extractor"
    SUMMARY = "summary"
    GENERAL = "general"


class RouteDecision(BaseModel):
    """Auto-router output."""

    model_config = {"extra": "forbid"}

    agent: AgentKind
    reason: str = Field(..., max_length=300)
    sensitive: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
