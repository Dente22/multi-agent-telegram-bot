"""Aiogram 3.x message handlers for the multi-agent bot."""

from __future__ import annotations

from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.router import AgentRouter
from app.bot.keyboards import main_menu_keyboard
from app.bot.middlewares import detect_lang
from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.core.security import SanitizationError
from app.services.document_loader import DocumentLoadError, load_document_text
from app.services.vector_store import VectorStore
from app.services.whisper_service import WhisperService

logger = get_logger(__name__)
router = Router(name="main")

HELP_RU = """\
Я — multi-agent корпоративный бот.

Команды:
/start — приветствие
/help — справка
/ask <вопрос> — RAG по загруженным документам
/task <текст> — извлечение задач (JSON + валидация)
/summary <обновления> — дневная сводка

Также можно:
• отправить голосовое — транскрипция + авто-роутинг
• загрузить .pdf / .txt / .docx — индексация в pgvector
• просто написать текст — авто-роутер выберет агента

Sensitive-запросы идут только через on-prem Ollama.
"""

HELP_EN = """\
I am an enterprise multi-agent bot.

Commands:
/start — welcome
/help — this help
/ask <question> — RAG over uploaded documents
/task <text> — structured task extraction
/summary <updates> — daily digest

Also supported:
• voice messages — transcription + auto-routing
• upload .pdf / .txt / .docx — pgvector indexing
• free text — auto-router picks an agent

Sensitive requests are routed strictly through on-prem Ollama.
"""


def _lang_from_message(message: Message, text: str | None = None) -> str:
    code = message.from_user.language_code if message.from_user else None
    return detect_lang(text or message.text, code)


async def _session() -> AsyncSession:
    factory = get_session_factory()
    return factory()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    lang = _lang_from_message(message)
    if lang.startswith("ru"):
        text = (
            "Привет! Я Multi-Agent Bot для корпоративной автоматизации.\n"
            "On-Premise LLM · RAG · Structured Outputs · Workflows.\n\n"
            "Отправьте /help для списка команд."
        )
    else:
        text = (
            "Hi! I'm a Multi-Agent Bot for enterprise automation.\n"
            "On-Premise LLM · RAG · Structured Outputs · Workflows.\n\n"
            "Send /help for commands."
        )
    await message.answer(text, reply_markup=main_menu_keyboard(lang=lang))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    lang = _lang_from_message(message)
    await message.answer(HELP_RU if lang.startswith("ru") else HELP_EN)


@router.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject) -> None:
    query = (command.args or "").strip()
    lang = _lang_from_message(message, query)
    if not query:
        await message.answer(
            "Использование: /ask <вопрос>" if lang.startswith("ru") else "Usage: /ask <question>"
        )
        return
    await _dispatch_command("ask", query, message, lang)


@router.message(Command("task"))
async def cmd_task(message: Message, command: CommandObject) -> None:
    payload = (command.args or "").strip()
    lang = _lang_from_message(message, payload)
    if not payload:
        await message.answer(
            "Использование: /task <текст задачи>"
            if lang.startswith("ru")
            else "Usage: /task <task text>"
        )
        return
    await _dispatch_command("task", payload, message, lang)


@router.message(Command("summary"))
async def cmd_summary(message: Message, command: CommandObject) -> None:
    payload = (command.args or "").strip()
    lang = _lang_from_message(message, payload)
    if not payload:
        await message.answer(
            "Использование: /summary <обновления>"
            if lang.startswith("ru")
            else "Usage: /summary <updates>"
        )
        return
    await _dispatch_command("summary", payload, message, lang)


@router.message(F.voice | F.audio)
async def handle_voice(message: Message, bot: Bot) -> None:
    """Transcribe voice and auto-route to an agent."""
    lang = _lang_from_message(message)
    tg_file = message.voice or message.audio
    if tg_file is None:
        return

    settings = get_settings()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    local_path = upload_dir / f"voice_{message.from_user.id}_{tg_file.file_unique_id}.ogg"

    await message.answer("🎧 Транскрибирую..." if lang.startswith("ru") else "🎧 Transcribing...")
    try:
        await bot.download(tg_file, destination=local_path)
        transcript = await WhisperService().transcribe(local_path)
    except Exception as exc:
        logger.exception("voice_failed", error=str(exc))
        await message.answer(
            f"Не удалось распознать голос: {exc}"
            if lang.startswith("ru")
            else f"Voice transcription failed: {exc}"
        )
        return
    finally:
        if local_path.exists():
            local_path.unlink(missing_ok=True)

    await message.answer(
        ("Распознано:\n" if lang.startswith("ru") else "Transcript:\n") + transcript
    )
    await _dispatch_auto(transcript, message, lang)


@router.message(F.document)
async def handle_document(message: Message, bot: Bot) -> None:
    """Ingest uploaded PDF/TXT/DOCX into pgvector store."""
    lang = _lang_from_message(message)
    doc = message.document
    if doc is None or not doc.file_name:
        return

    suffix = Path(doc.file_name).suffix.lower()
    if suffix not in {".pdf", ".txt", ".docx", ".md"}:
        await message.answer(
            "Поддерживаются: .pdf, .txt, .docx"
            if lang.startswith("ru")
            else "Supported: .pdf, .txt, .docx"
        )
        return

    settings = get_settings()
    if doc.file_size and doc.file_size > settings.max_upload_bytes:
        await message.answer(
            "Файл слишком большой." if lang.startswith("ru") else "File is too large."
        )
        return

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    local_path = upload_dir / f"{message.from_user.id}_{doc.file_unique_id}_{doc.file_name}"

    await message.answer(
        "📥 Индексирую документ..." if lang.startswith("ru") else "📥 Indexing document..."
    )
    try:
        await bot.download(doc, destination=local_path)
        text = await load_document_text(local_path)
        session = await _session()
        async with session:
            store = VectorStore(session)
            saved = await store.add_document(
                filename=doc.file_name,
                content_type=doc.mime_type or "application/octet-stream",
                text_content=text,
                owner_user_id=message.from_user.id,
                chat_id=message.chat.id,
                storage_path=str(local_path),
            )
            await session.commit()
        await message.answer(
            f"✅ Документ «{saved.filename}» проиндексирован. Используйте /ask"
            if lang.startswith("ru")
            else f"✅ Indexed «{saved.filename}». Use /ask to query."
        )
    except (DocumentLoadError, OSError) as exc:
        await message.answer(
            f"Ошибка загрузки: {exc}" if lang.startswith("ru") else f"Upload error: {exc}"
        )
    except Exception as exc:
        logger.exception("document_ingest_failed", error=str(exc))
        await message.answer(
            f"Ошибка индексации: {exc}" if lang.startswith("ru") else f"Indexing failed: {exc}"
        )


@router.message(F.text)
async def handle_text(message: Message) -> None:
    """Auto-route plain text (skip menu button labels that look like commands)."""
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    # Soft shortcuts from reply keyboard
    lowered = text.lower()
    if "справка" in lowered or text in {"❓ Help", "❓ Справка"}:
        await cmd_help(message)
        return
    if text.startswith("📄") or text.startswith("✅") or text.startswith("📊"):
        await message.answer(
            "Укажите текст после команды, например:\n/ask Что в политике отпусков?"
            if _lang_from_message(message).startswith("ru")
            else "Provide text after a command, e.g.\n/ask What is the leave policy?"
        )
        return

    lang = _lang_from_message(message, text)
    await _dispatch_auto(text, message, lang)


async def _dispatch_command(command: str, payload: str, message: Message, lang: str) -> None:
    assert message.from_user is not None
    session = await _session()
    async with session:
        try:
            agent_router = AgentRouter()
            result = await agent_router.route_command(
                command,
                payload,
                session=session,
                user_id=message.from_user.id,
                chat_id=message.chat.id,
                lang=lang,
            )
            await session.commit()
            await message.answer(result.text)
        except SanitizationError as exc:
            await message.answer(f"⚠️ {exc}")
        except Exception as exc:
            logger.exception("command_failed", command=command, error=str(exc))
            await message.answer(
                f"Ошибка агента: {exc}" if lang.startswith("ru") else f"Agent error: {exc}"
            )


async def _dispatch_auto(text: str, message: Message, lang: str) -> None:
    assert message.from_user is not None
    session = await _session()
    async with session:
        try:
            agent_router = AgentRouter()
            result = await agent_router.route_auto(
                text,
                session=session,
                user_id=message.from_user.id,
                chat_id=message.chat.id,
                lang=lang,
            )
            await session.commit()
            await message.answer(result.text)
        except SanitizationError as exc:
            await message.answer(f"⚠️ {exc}")
        except Exception as exc:
            logger.exception("auto_route_failed", error=str(exc))
            await message.answer(
                f"Ошибка: {exc}" if lang.startswith("ru") else f"Error: {exc}"
            )


def setup_routers() -> Router:
    """Return the root bot router."""
    return router
