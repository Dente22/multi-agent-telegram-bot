"""pgvector-backed document store with per-chat and personal isolation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import GLOBAL_KB_CHAT_ID
from app.models.document import Document, DocumentChunk
from app.schemas.rag import SourceCitation
from app.services.embeddings import EmbeddingService


@dataclass
class RetrievedChunk:
    chunk: DocumentChunk
    filename: str
    score: float


class VectorStore:
    """Ingest and search document chunks scoped by chat/user."""

    def __init__(self, session: AsyncSession, embedder: EmbeddingService | None = None) -> None:
        self.session = session
        self.embedder = embedder
        self.settings = get_settings()

    async def add_document(
        self,
        *,
        filename: str,
        content_type: str,
        text_content: str,
        owner_user_id: int,
        chat_id: int,
        storage_path: str | None = None,
    ) -> Document:
        """Chunk, embed, and persist a document for a chat/user scope."""
        doc = Document(
            filename=filename,
            content_type=content_type,
            owner_user_id=owner_user_id,
            chat_id=chat_id,
            storage_path=storage_path,
        )
        self.session.add(doc)
        await self.session.flush()

        chunks = _split_text(
            text_content,
            chunk_size=self.settings.chunk_size,
            overlap=self.settings.chunk_overlap,
        )
        embedder = self.embedder or EmbeddingService(self.settings)
        owns = self.embedder is None
        if owns:
            await embedder.__aenter__()
        try:
            vectors = await embedder.embed_many(chunks)
        finally:
            if owns:
                await embedder.__aexit__(None, None, None)

        for idx, (content, vector) in enumerate(zip(chunks, vectors, strict=True)):
            chunk = DocumentChunk(
                document_id=doc.id,
                chunk_index=idx,
                content=content,
                page=None,
                owner_user_id=owner_user_id,
                chat_id=chat_id,
            )
            self.session.add(chunk)
            await self.session.flush()
            if self.settings.is_postgres:
                await self.session.execute(
                    text(
                        "UPDATE document_chunks SET embedding = CAST(:emb AS vector) WHERE id = :id"
                    ),
                    {"emb": _vector_literal(vector), "id": chunk.id},
                )
        await self.session.flush()
        return doc

    async def delete_by_filename(
        self,
        *,
        filename: str,
        chat_id: int,
        owner_user_id: int | None = None,
    ) -> int:
        """Delete documents with the same filename in a scope (for re-ingest)."""
        stmt = select(Document).where(
            Document.filename == filename,
            Document.chat_id == chat_id,
        )
        if owner_user_id is not None:
            stmt = stmt.where(Document.owner_user_id == owner_user_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        for doc in rows:
            await self.session.delete(doc)
        await self.session.flush()
        return len(rows)

    async def similarity_search(
        self,
        *,
        query: str,
        owner_user_id: int,
        chat_id: int,
        top_k: int | None = None,
        include_personal: bool = True,
        include_global_kb: bool = True,
    ) -> list[RetrievedChunk]:
        """
        Search chunks visible to the user:
        - current chat docs
        - personal docs (owner_user_id)
        - global company knowledge base (chat_id = 0)
        """
        k = top_k or self.settings.rag_top_k
        embedder = self.embedder or EmbeddingService(self.settings)
        owns = self.embedder is None
        if owns:
            await embedder.__aenter__()
        try:
            query_vec = await embedder.embed(query)
        finally:
            if owns:
                await embedder.__aexit__(None, None, None)

        if not self.settings.is_postgres:
            return await self._fallback_keyword_search(
                query=query,
                owner_user_id=owner_user_id,
                chat_id=chat_id,
                top_k=k,
                include_global_kb=include_global_kb,
            )

        sql = text(
            """
            SELECT c.id, c.document_id, c.content, c.page, d.filename,
                   1 - (c.embedding <=> CAST(:q AS vector)) AS score
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.embedding IS NOT NULL
              AND (
                    c.chat_id = :chat_id
                 OR (:include_personal AND c.owner_user_id = :uid)
                 OR (:include_global AND c.chat_id = :global_chat_id)
              )
            ORDER BY c.embedding <=> CAST(:q AS vector)
            LIMIT :k
            """
        )
        rows = (
            await self.session.execute(
                sql,
                {
                    "q": _vector_literal(query_vec),
                    "chat_id": chat_id,
                    "uid": owner_user_id,
                    "include_personal": include_personal,
                    "include_global": include_global_kb,
                    "global_chat_id": GLOBAL_KB_CHAT_ID,
                    "k": k,
                },
            )
        ).mappings().all()

        results: list[RetrievedChunk] = []
        for row in rows:
            chunk = DocumentChunk(
                id=row["id"],
                document_id=row["document_id"],
                chunk_index=0,
                content=row["content"],
                page=row["page"],
                owner_user_id=owner_user_id,
                chat_id=chat_id,
            )
            results.append(
                RetrievedChunk(
                    chunk=chunk,
                    filename=row["filename"],
                    score=float(row["score"] or 0.0),
                )
            )
        return results

    async def _fallback_keyword_search(
        self,
        *,
        query: str,
        owner_user_id: int,
        chat_id: int,
        top_k: int,
        include_global_kb: bool = True,
    ) -> list[RetrievedChunk]:
        conditions = [
            (DocumentChunk.chat_id == chat_id) | (DocumentChunk.owner_user_id == owner_user_id)
        ]
        if include_global_kb:
            conditions.append(DocumentChunk.chat_id == GLOBAL_KB_CHAT_ID)

        from sqlalchemy import or_

        stmt = (
            select(DocumentChunk, Document.filename)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(or_(*conditions))
            .limit(50)
        )
        rows = (await self.session.execute(stmt)).all()
        q = query.lower()
        scored: list[RetrievedChunk] = []
        for chunk, filename in rows:
            score = 1.0 if q in chunk.content.lower() else 0.2
            scored.append(RetrievedChunk(chunk=chunk, filename=filename, score=score))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    @staticmethod
    def to_citations(retrieved: list[RetrievedChunk]) -> list[SourceCitation]:
        return [
            SourceCitation(
                document_id=str(item.chunk.document_id),
                chunk_id=str(item.chunk.id),
                filename=item.filename,
                excerpt=item.chunk.content[:400],
                score=round(min(max(item.score, 0.0), 1.0), 4),
                page=item.chunk.page,
            )
            for item in retrieved
        ]


def _split_text(text_content: str, *, chunk_size: int, overlap: int) -> list[str]:
    text_content = text_content.strip()
    if not text_content:
        return []
    chunks: list[str] = []
    start = 0
    n = len(text_content)
    while start < n:
        end = min(start + chunk_size, n)
        chunks.append(text_content[start:end])
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"
