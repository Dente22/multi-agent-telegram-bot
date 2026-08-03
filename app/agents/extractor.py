"""Structured Task Extractor agent with Pydantic validation retries."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sanitize_output, sanitize_user_text
from app.models.task import TaskRecord
from app.schemas.tasks import TASK_JSON_SCHEMA_HINT, TaskExtractionResult
from app.services.dates import normalize_deadline
from app.services.llm_engine import LLMEngine


def _extractor_system() -> str:
    today = date.today().isoformat()
    return f"""You are an enterprise task extraction agent.
Today's date is {today} (use this for relative deadlines).
Parse employee messages (text or transcribed voice) into structured tasks.
Return ONLY valid JSON matching this schema:
{TASK_JSON_SCHEMA_HINT}

Rules:
- Extract ALL actionable tasks from the message (array may be empty).
- priority must be one of: low, medium, high, critical.
- If text says "срочно/urgent/asap" → priority high or critical.
- deadline must be YYYY-MM-DD or null.
- Relative dates: "сегодня/today", "завтра/tomorrow", "пятница/Friday" → compute from today ({today}).
- Never invent past years. Deadlines must be today or in the future unless the text explicitly says a past date.
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
        user_prompt = (
            f"Today: {date.today().isoformat()}\n"
            f"Message:\n{cleaned}\n\n"
            "Return the JSON task extraction now."
        )

        owns_llm = self.llm is None
        llm = self.llm or LLMEngine()
        if owns_llm:
            await llm.__aenter__()
        try:
            result, _provider, _model, _retries = await llm.structured(
                system=_extractor_system(),
                user=user_prompt,
                schema=TaskExtractionResult,
            )
        finally:
            if owns_llm:
                await llm.__aexit__(None, None, None)

        for task in result.tasks:
            task.action_item = sanitize_output(task.action_item)
            if task.notes:
                task.notes = sanitize_output(task.notes)
            task.deadline = normalize_deadline(task.deadline, cleaned)

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

        if lang.startswith("ru"):
            lines = [
                "✅ <b>Задача разобрана и сохранена</b>",
                "",
                "Это режим <b>/task</b>: я превращаю текст в структуру "
                "(что сделать / приоритет / кто / срок) и пишу в базу.",
                "",
            ]
            for i, task in enumerate(result.tasks, start=1):
                deadline = task.deadline.isoformat() if task.deadline else "не указан"
                assignee = task.assignee or "не назначен"
                lines.append(
                    f"<b>{i}. {task.action_item}</b>\n"
                    f"• приоритет: <code>{task.priority.value}</code>\n"
                    f"• исполнитель: {assignee}\n"
                    f"• срок: {deadline}"
                )
            lines.extend(
                [
                    "",
                    f"Уверенность: {result.confidence:.0%}",
                    "Список сохранённых: /tasks",
                    "Спросить по регламентам: /ask …",
                ]
            )
        else:
            lines = [
                "✅ <b>Task parsed and saved</b>",
                "",
                "This is <b>/task</b> mode: I turn text into structured fields "
                "(action / priority / assignee / deadline) and store them.",
                "",
            ]
            for i, task in enumerate(result.tasks, start=1):
                deadline = task.deadline.isoformat() if task.deadline else "n/a"
                assignee = task.assignee or "unassigned"
                lines.append(
                    f"<b>{i}. {task.action_item}</b>\n"
                    f"• priority: <code>{task.priority.value}</code>\n"
                    f"• assignee: {assignee}\n"
                    f"• deadline: {deadline}"
                )
            lines.extend(
                [
                    "",
                    f"Confidence: {result.confidence:.0%}",
                    "Saved list: /tasks",
                    "Ask policies: /ask …",
                ]
            )
        return "\n".join(lines)
