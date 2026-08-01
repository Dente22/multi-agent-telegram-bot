"""Embedding service via Ollama with mock fallback."""

from __future__ import annotations

from typing import Self

import httpx

from app.core.config import Settings, get_settings
from app.services.mock_providers import mock_embedding


class EmbeddingService:
    """Generate dense embeddings for RAG chunks/queries."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        vectors = await self.embed_many([text])
        return vectors[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts."""
        if not texts:
            return []
        if self.settings.use_mocks or self.settings.llm_provider == "mock":
            # Still try Ollama if available when not forced mock
            if self.settings.llm_provider == "mock":
                return [
                    mock_embedding(t, self.settings.embedding_dimensions) for t in texts
                ]

        assert self._client is not None
        try:
            results: list[list[float]] = []
            for text in texts:
                response = await self._client.post(
                    f"{self.settings.ollama_base_url}/api/embeddings",
                    json={"model": self.settings.ollama_embed_model, "prompt": text},
                )
                response.raise_for_status()
                embedding = response.json().get("embedding")
                if not embedding:
                    raise ValueError("Empty embedding from Ollama")
                results.append([float(x) for x in embedding])
            return results
        except Exception:
            if self.settings.use_mocks:
                return [
                    mock_embedding(t, self.settings.embedding_dimensions) for t in texts
                ]
            raise
