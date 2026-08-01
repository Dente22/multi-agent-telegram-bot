"""Bot middlewares: whitelist, rate-limit, locale hints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.core.config import get_settings
from app.core.redis import check_rate_limit


class WhitelistMiddleware(BaseMiddleware):
    """Restrict access to allowed user/chat IDs when configured."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        settings = get_settings()
        user_ids = settings.allowed_user_id_set
        chat_ids = settings.allowed_chat_id_set

        if user_ids and event.from_user.id not in user_ids:
            await event.answer("Access denied. Contact the administrator.")
            return None
        if chat_ids and event.chat.id not in chat_ids:
            await event.answer("This chat is not authorized.")
            return None
        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """Redis-backed per-user rate limiting."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)
        try:
            allowed = await check_rate_limit(f"tg:{event.from_user.id}")
        except Exception:
            # Soft-fail when Redis is down (local demo / API-only)
            return await handler(event, data)
        if not allowed:
            await event.answer("Rate limit exceeded. Please wait a moment.")
            return None
        return await handler(event, data)


def detect_lang(text: str | None, language_code: str | None = None) -> str:
    """Heuristic locale detection for bilingual replies."""
    if language_code and language_code.startswith("ru"):
        return "ru"
    if text and any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in text):
        return "ru"
    if language_code:
        return language_code.split("-")[0]
    return "en"
