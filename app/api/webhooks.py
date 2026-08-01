"""Telegram webhook endpoint for production deployments."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, status
from aiogram.types import Update

from app.core.config import get_settings

router = APIRouter(tags=["telegram"])

_bot = None
_dispatcher = None


def bind_bot(bot, dispatcher) -> None:
    """Attach aiogram instances created in app lifespan."""
    global _bot, _dispatcher
    _bot = bot
    _dispatcher = dispatcher


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    """Receive Telegram updates via webhook."""
    settings = get_settings()
    if settings.telegram_webhook_secret:
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid secret")

    if _bot is None or _dispatcher is None:
        raise HTTPException(status_code=503, detail="Bot is not ready")

    data = await request.json()
    update = Update.model_validate(data, context={"bot": _bot})
    await _dispatcher.feed_update(_bot, update)
    return {"ok": True}
