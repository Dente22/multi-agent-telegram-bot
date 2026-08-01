"""Document RAG agent with exact source citations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import sanitize_output, sanitize_user_text
from app.schemas.rag import RAGAnswer
from app.services.llm_engine import LLMEngine
from app.services.vector_store import VectorStore

RAG_SYSTEM = """You are an enterprise Document RAG agent.
Answer ONLY using the provided context chunks.
Return ONLY valid JSON:
{
  "answer": "string",
  "confidence_score": 0.0,
  "sources": [
    {
      "document_id": "string",
      "chunk_id": "string",
      "filename": "string",
      "excerpt": "short quote",
      "score": 0.0,
      "page": null
    }
  ]
}
Rules:
- Never invent facts outside the context.
- Cite the chunks you used.
- No markdown fences.
"""


class RAGAgent:
    """Retrieve relevant chunks and produce a grounded answer with citations."""

    def __init__(self, llm: LLMEngine | None = None) -> None:
        self.llm = llm
        self.settings = get_settings()

    async def ask(
        self,
        question: str,
        *,
        session: AsyncSession,
        owner_user_id: int,
        chat_id: int,
    ) -> RAGAnswer:
        cleaned = sanitize_user_text(question, field_name="question")
        store = VectorStore(session)
        retrieved = await store.similarity_search(
            query=cleaned,
            owner_user_id=owner_user_id,
            chat_id=chat_id,
        )
        citations = VectorStore.to_citations(retrieved)

        if not retrieved:
            return RAGAnswer(
                answer=(
                    "I could not find relevant documents in this chat or your personal library. "
                    "Upload a .pdf / .txt / .docx file first."
                ),
                confidence_score=0.1,
                sources=[],
            )

        context = [
            {
                "document_id": c.document_id,
                "chunk_id": c.chunk_id,
                "filename": c.filename,
                "excerpt": c.excerpt,
                "score": c.score,
                "page": c.page,
            }
            for c in citations
        ]
        user_prompt = (
            f"Question:\n{cleaned}\n\n"
            f"Context chunks (JSON):\n{context}\n\n"
            "Return the grounded JSON answer now."
        )

        owns_llm = self.llm is None
        llm = self.llm or LLMEngine()
        if owns_llm:
            await llm.__aenter__()
        try:
            answer, _provider, _model, _retries = await llm.structured(
                system=RAG_SYSTEM,
                user=user_prompt,
                schema=RAGAnswer,
            )
        finally:
            if owns_llm:
                await llm.__aexit__(None, None, None)

        answer.answer = sanitize_output(answer.answer)
        if not answer.sources:
            answer.sources = citations[:3]
        if answer.confidence_score < self.settings.min_confidence_threshold:
            answer.answer = (
                "Low confidence: " + answer.answer
            )
        return answer

    @staticmethod
    def format_for_telegram(answer: RAGAnswer, *, lang: str = "ru") -> str:
        sources_title = "Источники:" if lang.startswith("ru") else "Sources:"
        lines = [answer.answer, "", f"{sources_title}"]
        if not answer.sources:
            lines.append("—")
        for src in answer.sources:
            page = f", p.{src.page}" if src.page else ""
            lines.append(f"• {src.filename}{page} (score={src.score:.2f})")
            lines.append(f"  \"{src.excerpt[:180]}\"")
        lines.append(f"confidence: {answer.confidence_score:.2f}")
        return "\n".join(lines)
