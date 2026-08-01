"""Structured task extraction schemas with strict validation."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Priority(str, Enum):
    """Task priority levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExtractedTask(BaseModel):
    """Single structured action item extracted from free-form text/voice."""

    model_config = {"extra": "forbid"}

    action_item: str = Field(..., min_length=3, max_length=500)
    priority: Priority = Priority.MEDIUM
    assignee: str | None = Field(default=None, max_length=120)
    deadline: date | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("assignee", "notes", mode="before")
    @classmethod
    def _strip_optional(cls, value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("action_item", mode="before")
    @classmethod
    def _require_action(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("action_item must be at least 3 characters")
        return cleaned

    @field_validator("deadline", mode="before")
    @classmethod
    def _parse_deadline(cls, value: Any) -> Any:
        if value in (None, "", "null", "none", "N/A"):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            text = value.strip().replace("/", "-")
            for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y"):
                try:
                    return datetime.strptime(text, fmt).date()
                except ValueError:
                    continue
            raise ValueError("deadline must be YYYY-MM-DD or DD.MM.YYYY")
        return value


class TaskExtractionResult(BaseModel):
    """Container returned by the Structured Task Extractor agent."""

    model_config = {"extra": "forbid"}

    tasks: list[ExtractedTask] = Field(default_factory=list, min_length=0)
    source_language: str | None = Field(default=None, max_length=16)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _normalize_empty(self) -> TaskExtractionResult:
        if self.tasks is None:
            self.tasks = []
        return self


# JSON schema hint embedded in LLM prompts
TASK_JSON_SCHEMA_HINT = """
{
  "tasks": [
    {
      "action_item": "string (required)",
      "priority": "low|medium|high|critical",
      "assignee": "string or null",
      "deadline": "YYYY-MM-DD or null",
      "notes": "string or null"
    }
  ],
  "source_language": "ru|en|null",
  "confidence": 0.0
}
""".strip()
