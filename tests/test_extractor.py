"""Task extractor agent tests (mock LLM)."""

import pytest

from app.agents.extractor import TaskExtractorAgent
from app.core.config import get_settings
from app.services.llm_engine import LLMEngine


@pytest.mark.asyncio
async def test_extractor_returns_validated_tasks(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "use_mocks", True)
    monkeypatch.setattr(settings, "llm_provider", "mock")

    async with LLMEngine(settings=settings) as llm:
        agent = TaskExtractorAgent(llm=llm)
        result = await agent.extract(
            "Срочно: подготовить отчёт к пятнице, исполнитель: Анна",
            persist=False,
        )

    assert result.tasks
    text = TaskExtractorAgent.format_for_telegram(result, lang="ru")
    assert "Задача разобрана и сохранена" in text
    assert "/tasks" in text
