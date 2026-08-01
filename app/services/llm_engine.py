"""LLM engine: Ollama primary, Gemini fallback, sensitive on-prem gate, JSON retries."""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Self, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.security import is_sensitive_request
from app.services.mock_providers import mock_chat_completion

logger = get_logger(__name__)

ProviderName = Literal["ollama", "gemini", "mock"]
T = TypeVar("T", bound=BaseModel)


class LLMEngineError(RuntimeError):
    """Raised when no provider can return a valid response."""


class LLMEngine:
    """
    Async LLM orchestration.

    Policy:
    - Sensitive requests → Ollama only (or mock), never Gemini.
    - Non-sensitive → Ollama first, Gemini fallback on transport failure.
    - Structured outputs → Pydantic validation with automatic retries.
    """

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
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("LLMEngine HTTP client is not initialized")
        return self._client

    async def chat(
        self,
        *,
        system: str,
        user: str,
        sensitive: bool | None = None,
        json_mode: bool = False,
    ) -> tuple[str, ProviderName, str]:
        """
        Free-form chat completion.

        Returns:
            (content, provider, model)
        """
        force_sensitive = is_sensitive_request(user) if sensitive is None else sensitive
        provider = await self._resolve_provider(force_onprem=force_sensitive)
        model = self._model_for(provider)
        content = await self._chat(
            provider=provider,
            model=model,
            system=system,
            user=user,
            json_mode=json_mode,
        )
        return content, provider, model

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        sensitive: bool | None = None,
    ) -> tuple[T, ProviderName, str, int]:
        """
        Guaranteed structured output via Pydantic validation + retries.

        Returns:
            (parsed_model, provider, model, retry_count)
        """
        force_sensitive = is_sensitive_request(user) if sensitive is None else sensitive
        provider = await self._resolve_provider(force_onprem=force_sensitive)
        model = self._model_for(provider)
        feedback = ""
        last_error: Exception | None = None

        for attempt in range(self.settings.llm_max_retries + 1):
            prompt = user if not feedback else f"{user}\n\nCorrection:\n{feedback}"
            try:
                raw = await self._chat(
                    provider=provider,
                    model=model,
                    system=system,
                    user=prompt,
                    json_mode=True,
                )
                payload = self._parse_json_payload(raw)
                parsed = schema.model_validate(payload)
                return parsed, provider, model, attempt
            except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
                last_error = exc
                feedback = (
                    f"Previous response failed validation: {exc}. "
                    "Return corrected JSON only. No markdown."
                )
                logger.warning("structured_output_retry", attempt=attempt, error=str(exc))
            except httpx.HTTPError as exc:
                last_error = exc
                if provider == "ollama" and not force_sensitive:
                    next_provider = await self._fallback_provider()
                    if next_provider and next_provider != provider:
                        provider = next_provider
                        model = self._model_for(provider)
                        feedback = ""
                        logger.warning("llm_fallback", from_="ollama", to=provider)
                        continue
                break

        raise LLMEngineError(f"Failed to obtain schema-valid output: {last_error}")

    async def _resolve_provider(self, *, force_onprem: bool) -> ProviderName:
        mode = self.settings.llm_provider

        if mode == "mock":
            return "mock"

        if mode == "gemini":
            if force_onprem:
                raise LLMEngineError("Sensitive requests cannot use Gemini (on-prem isolation)")
            if self.settings.gemini_api_key:
                return "gemini"
            if self.settings.use_mocks:
                return "mock"
            raise LLMEngineError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")

        if mode == "ollama":
            if await self._ollama_alive():
                return "ollama"
            if self.settings.use_mocks:
                return "mock"
            raise LLMEngineError("Ollama is unavailable")

        # auto
        if await self._ollama_alive():
            return "ollama"
        if force_onprem:
            if self.settings.use_mocks:
                return "mock"
            raise LLMEngineError("Sensitive request requires Ollama (unavailable)")
        if self.settings.gemini_api_key:
            return "gemini"
        if self.settings.use_mocks:
            return "mock"
        raise LLMEngineError("No LLM provider available")

    async def _fallback_provider(self) -> ProviderName | None:
        if self.settings.gemini_api_key:
            return "gemini"
        if self.settings.use_mocks:
            return "mock"
        return None

    async def _ollama_alive(self) -> bool:
        try:
            response = await self.client.get(f"{self.settings.ollama_base_url}/api/tags")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _model_for(self, provider: ProviderName) -> str:
        if provider == "ollama":
            return self.settings.ollama_model
        if provider == "gemini":
            return self.settings.gemini_model
        return "mock-llm"

    async def _chat(
        self,
        *,
        provider: ProviderName,
        model: str,
        system: str,
        user: str,
        json_mode: bool,
    ) -> str:
        if provider == "mock":
            return mock_chat_completion(system=system, user=user, json_mode=json_mode)

        if provider == "ollama":
            payload: dict[str, Any] = {
                "model": model,
                "stream": False,
                "options": {"temperature": self.settings.llm_temperature},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if json_mode:
                payload["format"] = "json"
            response = await self.client.post(
                f"{self.settings.ollama_base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content")
            if not content:
                raise ValueError("Ollama returned empty content")
            return str(content)

        # Gemini (REST generateContent)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.settings.llm_temperature,
            },
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"

        response = await self.client.post(
            url,
            params={"key": self.settings.gemini_api_key},
            json=body,
        )
        response.raise_for_status()
        data = response.json()
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Gemini returned unexpected payload: {data}") from exc
        if not content:
            raise ValueError("Gemini returned empty content")
        return str(content)

    @staticmethod
    def _parse_json_payload(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        if not isinstance(data, dict):
            raise TypeError("LLM JSON root must be an object")
        return data
