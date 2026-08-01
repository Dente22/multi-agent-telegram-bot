"""Summary & analytics agent schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DailySummary(BaseModel):
    """Structured daily operational summary."""

    model_config = {"extra": "forbid"}

    headline: str = Field(..., min_length=3, max_length=200)
    bullet_points: list[str] = Field(default_factory=list, max_length=20)
    action_items: list[str] = Field(default_factory=list, max_length=20)
    risks: list[str] = Field(default_factory=list, max_length=10)
    estimated_time_saved_pct: int = Field(default=30, ge=0, le=100)
