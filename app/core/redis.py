"""Async Redis client for caching and rate limiting."""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import get_settings

_redis: Redis | None = None


async def get_redis() -> Redis:
    """Return a shared Redis connection."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def check_rate_limit(key: str) -> bool:
    """
    Sliding-window rate limit.

    Returns True if the request is allowed, False if limited.
    """
    settings = get_settings()
    redis = await get_redis()
    bucket = f"rl:{key}"
    count = await redis.incr(bucket)
    if count == 1:
        await redis.expire(bucket, settings.rate_limit_window_seconds)
    return count <= settings.rate_limit_requests
