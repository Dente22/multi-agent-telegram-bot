"""Application entrypoint: FastAPI + Aiogram multi-agent service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI

from app.api import health, webhooks
from app.bot.handlers import setup_routers
from app.bot.middlewares import RateLimitMiddleware, WhitelistMiddleware
from app.core.config import get_settings
from app.core.database import dispose_db, init_db
from app.core.logging import get_logger, setup_logging
from app.core.redis import close_redis
from app.services.knowledge_ingest import ingest_knowledge_dir

logger = get_logger(__name__)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.message.middleware(WhitelistMiddleware())
    dp.message.middleware(RateLimitMiddleware())
    dp.include_router(setup_routers())
    return dp


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(debug=settings.debug)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

    await init_db()
    logger.info("database_ready")

    if settings.auto_ingest_knowledge:
        try:
            stats = await ingest_knowledge_dir(settings.knowledge_dir, settings=settings)
            logger.info("knowledge_ready", **stats)
        except Exception as exc:
            logger.exception("knowledge_ingest_failed", error=str(exc))

    bot: Bot | None = None
    dp: Dispatcher | None = None
    polling_task: asyncio.Task | None = None

    if settings.telegram_bot_token:
        bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dp = create_dispatcher()
        webhooks.bind_bot(bot, dp)

        if settings.telegram_mode == "webhook" and settings.telegram_webhook_url:
            await bot.set_webhook(
                settings.telegram_webhook_url,
                secret_token=settings.telegram_webhook_secret or None,
            )
            logger.info("telegram_webhook_set", url=settings.telegram_webhook_url)
        else:
            await bot.delete_webhook(drop_pending_updates=True)
            polling_task = asyncio.create_task(dp.start_polling(bot))
            logger.info("telegram_polling_started")
    else:
        logger.warning("telegram_bot_token_missing", hint="API-only / mock mode")

    app.state.bot = bot
    app.state.dp = dp

    yield

    if polling_task:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
    if bot:
        await bot.session.close()
    await close_redis()
    await dispose_db()
    logger.info("shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
    )
    application.include_router(health.router, prefix=settings.api_v1_prefix)
    application.include_router(webhooks.router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
