"""Structured Task Extractor agent with Pydantic validation retries."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sanitize_output, sanitize_user_text
from app.models.task import TaskRecord
from app.schemas.tasks import TASK_JSON_SCHEMA_HINT, TaskExtractionResult
from app.services.llm_engine import LLMEngine

EXTRACTOR_SYSTEM = f"""You are an enterprise task extraction agent.
Parse employee messages (text or transcribed voice) into structured tasks.
Return ONLY valid JSON matching this schema:
{TASK_JSON_SCHEMA_HINT}

Rules:
- Extract ALL actionable tasks from the message (array may be empty).
- priority must be one of: low, medium, high, critical.
- deadline must be YYYY-MM-DD or null.
- assignee is a person name/username or null.
- Do not invent facts that are not implied by the text.
- No markdown fences.
"""


class TaskExtractorAgent:
    """Parse raw employee text into validated JSON tasks."""

    def __init__(self, llm: LLMEngine | None = None) -> None:
        self.llm = llm

    async def extract(
        self,
        raw_text: str,
        *,
        session: AsyncSession | None = None,
        source_user_id: int | None = None,
        chat_id: int | None = None,
        persist: bool = True,
    ) -> TaskExtractionResult:
        """Extract and optionally persist structured tasks."""
        cleaned = sanitize_user_text(raw_text, field_name="message")
        user_prompt = f"Message:\n{cleaned}\n\nReturn the JSON task extraction now."

        owns_llm = self.llm is None
        llm = self.llm or LLMEngine()
        if owns_llm:
            await llm.__aenter__()
        try:
            result, _provider, _model, _retries = await llm.structured(
                system=EXTRACTOR_SYSTEM,
                user=user_prompt,
                schema=TaskExtractionResult,
            )
        finally:
            if owns_llm:
                await llm.__aexit__(None, None, None)

        # Sanitize string fields
        for task in result.tasks:
            task.action_item = sanitize_output(task.action_item)
            if task.notes:
                task.notes = sanitize_output(task.notes)

        if persist and session is not None and source_user_id is not None and chat_id is not None:
            for task in result.tasks:
                session.add(
                    TaskRecord(
                        action_item=task.action_item,
                        priority=task.priority.value,
                        assignee=task.assignee,
                        deadline=task.deadline,
                        notes=task.notes,
                        source_user_id=source_user_id,
                        chat_id=chat_id,
                    )
                )
            await session.flush()

        return result

    @staticmethod
    def format_for_telegram(result: TaskExtractionResult, *, lang: str = "ru") -> str:
        """Human-readable Telegram message for extracted tasks."""
        if not result.tasks:
            return (
                "Задачи не найдены в сообщении."
                if lang.startswith("ru")
                else "No actionable tasks found."
            )

        lines: list[str] = []
        header = "Извлечённые задачи:" if lang.startswith("ru") else "Extracted tasks:"
        lines.append(header)
        for i, task in enumerate(result.tasks, start=1):
            deadline = task.deadline.isoformat() if task.deadline else "—"
            assignee = task.assignee or "—"
            lines.append(
                f"{i}. [{task.priority.value}] {task.action_item}\n"
                f"   → {assignee} | {deadline}"
            )
        lines.append(f"confidence: {result.confidence:.2f}")
        return "\n".join(lines)
