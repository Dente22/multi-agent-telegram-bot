"""Multi-agent router: explicit commands + auto-routing for free text/voice."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.extractor import TaskExtractorAgent
from app.agents.rag_agent import RAGAgent
from app.agents.summary_agent import SummaryAgent
from app.core.security import is_sensitive_request, sanitize_user_text
from app.schemas.routing import AgentKind, RouteDecision
from app.services.llm_engine import LLMEngine

ROUTER_SYSTEM = """You are a multi-agent router for an enterprise Telegram bot.
Choose exactly one agent:
- rag: document questions, policies, uploaded files
- extractor: action items, tasks, deadlines, assignees
- summary: daily digests, status updates, analytics
- general: greetings or unclear intent

Return ONLY JSON:
{
  "agent": "rag|extractor|summary|general",
  "reason": "short reason",
  "sensitive": false,
  "confidence": 0.0
}
"""


@dataclass
class AgentResponse:
    text: str
    agent: AgentKind
    sensitive: bool = False


class AgentRouter:
    """Dispatch user messages to specialist agents."""

    def __init__(self, llm: LLMEngine | None = None) -> None:
        self.llm = llm
        self.rag = RAGAgent(llm)
        self.extractor = TaskExtractorAgent(llm)
        self.summary = SummaryAgent(llm)

    async def route_command(
        self,
        command: str,
        payload: str,
        *,
        session: AsyncSession,
        user_id: int,
        chat_id: int,
        lang: str = "ru",
    ) -> AgentResponse:
        """Handle explicit bot commands."""
        cmd = command.lower().lstrip("/")
        if cmd == "ask":
            answer = await self.rag.ask(
                payload,
                session=session,
                owner_user_id=user_id,
                chat_id=chat_id,
            )
            return AgentResponse(
                text=RAGAgent.format_for_telegram(answer, lang=lang),
                agent=AgentKind.RAG,
                sensitive=is_sensitive_request(payload),
            )
        if cmd == "task":
            result = await self.extractor.extract(
                payload,
                session=session,
                source_user_id=user_id,
                chat_id=chat_id,
            )
            return AgentResponse(
                text=TaskExtractorAgent.format_for_telegram(result, lang=lang),
                agent=AgentKind.EXTRACTOR,
            )
        if cmd == "summary":
            summary = await self.summary.summarize(payload)
            return AgentResponse(
                text=SummaryAgent.format_for_telegram(summary, lang=lang),
                agent=AgentKind.SUMMARY,
            )
        raise ValueError(f"Unknown command: {command}")

    async def route_auto(
        self,
        text: str,
        *,
        session: AsyncSession,
        user_id: int,
        chat_id: int,
        lang: str = "ru",
    ) -> AgentResponse:
        """Auto-route free-form text/voice transcripts."""
        cleaned = sanitize_user_text(text)
        decision = await self._decide(cleaned)

        if decision.agent == AgentKind.RAG:
            return await self.route_command(
                "ask", cleaned, session=session, user_id=user_id, chat_id=chat_id, lang=lang
            )
        if decision.agent == AgentKind.EXTRACTOR:
            return await self.route_command(
                "task", cleaned, session=session, user_id=user_id, chat_id=chat_id, lang=lang
            )
        if decision.agent == AgentKind.SUMMARY:
            return await self.route_command(
                "summary", cleaned, session=session, user_id=user_id, chat_id=chat_id, lang=lang
            )

        if lang.startswith("ru"):
            msg = (
                "Не уверен, какой агент нужен. Используйте:\n"
                "/ask <вопрос> — RAG по документам\n"
                "/task <текст> — извлечение задач\n"
                "/summary <обновления> — сводка"
            )
        else:
            msg = (
                "I'm not sure which agent to use. Try:\n"
                "/ask <question> — document RAG\n"
                "/task <text> — task extraction\n"
                "/summary <updates> — daily digest"
            )
        return AgentResponse(text=msg, agent=AgentKind.GENERAL, sensitive=decision.sensitive)

    async def _decide(self, text: str) -> RouteDecision:
        sensitive = is_sensitive_request(text)
        owns_llm = self.llm is None
        llm = self.llm or LLMEngine()
        if owns_llm:
            await llm.__aenter__()
        try:
            decision, _p, _m, _r = await llm.structured(
                system=ROUTER_SYSTEM,
                user=f"Message:\n{text}\n\nReturn routing JSON.",
                schema=RouteDecision,
                sensitive=sensitive,
            )
            decision.sensitive = decision.sensitive or sensitive
            return decision
        finally:
            if owns_llm:
                await llm.__aexit__(None, None, None)
