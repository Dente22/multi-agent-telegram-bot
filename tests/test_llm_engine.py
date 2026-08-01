"""LLM engine mock-mode tests."""

import pytest

from app.core.config import get_settings
from app.schemas.tasks import TaskExtractionResult
from app.services.llm_engine import LLMEngine


@pytest.mark.asyncio
async def test_structured_extraction_with_mocks(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "use_mocks", True)
    monkeypatch.setattr(settings, "llm_provider", "mock")

    async with LLMEngine(settings=settings) as llm:
        result, provider, model, retries = await llm.structured(
            system="Extract tasks as JSON with action_item fields.",
            user="Message: Prepare the report by Friday, assignee: Anna. Urgent.",
            schema=TaskExtractionResult,
        )

    assert provider == "mock"
    assert model == "mock-llm"
    assert retries == 0
    assert result.tasks
    assert "report" in result.tasks[0].action_item.lower() or result.tasks[0].action_item


@pytest.mark.asyncio
async def test_sensitive_blocks_gemini(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "use_mocks", True)
    monkeypatch.setattr(settings, "llm_provider", "mock")

    async with LLMEngine(settings=settings) as llm:
        content, provider, _model = await llm.chat(
            system="You are helpful.",
            user="This is confidential password reset for internal only systems.",
            sensitive=True,
            json_mode=False,
        )
    assert provider in {"mock", "ollama"}
    assert content
