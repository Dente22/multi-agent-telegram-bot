"""FastAPI dependency helpers."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """Validate X-API-Key for internal/admin endpoints."""
    settings = get_settings()
    if not x_api_key or x_api_key not in settings.api_key_set:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return x_api_key
