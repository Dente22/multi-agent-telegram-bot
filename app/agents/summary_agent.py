"""Summary & analytics agent for daily operational digests."""

from __future__ import annotations

from app.core.security import sanitize_output, sanitize_user_text
from app.schemas.summary import DailySummary
from app.services.llm_engine import LLMEngine

SUMMARY_SYSTEM = """You are an enterprise Summary & Analytics agent.
Summarize internal updates and surface routine action items.
Return ONLY valid JSON:
{
  "headline": "string",
  "bullet_points": ["string"],
  "action_items": ["string"],
  "risks": ["string"],
  "estimated_time_saved_pct": 30
}
No markdown fences.
"""


class SummaryAgent:
    """Produce structured daily summaries from raw updates."""

    def __init__(self, llm: LLMEngine | None = None) -> None:
        self.llm = llm

    async def summarize(self, updates_text: str) -> DailySummary:
        cleaned = sanitize_user_text(updates_text, field_name="updates")
        user_prompt = f"Internal updates:\n{cleaned}\n\nReturn the JSON summary now."

        owns_llm = self.llm is None
        llm = self.llm or LLMEngine()
        if owns_llm:
            await llm.__aenter__()
        try:
            result, _provider, _model, _retries = await llm.structured(
                system=SUMMARY_SYSTEM,
                user=user_prompt,
                schema=DailySummary,
            )
        finally:
            if owns_llm:
                await llm.__aexit__(None, None, None)

        result.headline = sanitize_output(result.headline)
        result.bullet_points = [sanitize_output(x) for x in result.bullet_points]
        result.action_items = [sanitize_output(x) for x in result.action_items]
        result.risks = [sanitize_output(x) for x in result.risks]
        return result

    @staticmethod
    def format_for_telegram(summary: DailySummary, *, lang: str = "ru") -> str:
        def bullets(items: list[str], empty: str = "• —") -> list[str]:
            return [f"• {item}" for item in items] if items else [empty]

        if lang.startswith("ru"):
            lines = [
                f"📋 {summary.headline}",
                "",
                "Ключевые пункты:",
                *bullets(summary.bullet_points),
                "",
                "Действия:",
                *bullets(summary.action_items),
                "",
                "Риски:",
                *bullets(summary.risks),
                "",
                f"Оценка экономии времени: ~{summary.estimated_time_saved_pct}%",
            ]
        else:
            lines = [
                f"📋 {summary.headline}",
                "",
                "Highlights:",
                *bullets(summary.bullet_points),
                "",
                "Actions:",
                *bullets(summary.action_items),
                "",
                "Risks:",
                *bullets(summary.risks),
                "",
                f"Est. time saved: ~{summary.estimated_time_saved_pct}%",
            ]
        return "\n".join(lines)
