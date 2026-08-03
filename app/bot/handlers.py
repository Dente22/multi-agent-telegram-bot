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
🤖 <b>Что я умею</b>

Я корпоративный multi-agent бот. Выберите сценарий:

<b>1) Ответы по документам (RAG)</b>
Уже подключена общая база знаний компании (+ ваши файлы).
Спросите, например:
<code>/ask Сколько дней отпуска в год?</code>
<code>/ask Как оформить авансовый отчёт?</code>
<code>/ask Что делать при утере пропуска?</code>
<code>/ask Как получить доступ к GitHub?</code>
Или загрузите свой .pdf / .txt / .docx и спросите через /ask.

<b>2) Извлечение задач</b>
Пришлите текст или голос, я верну структурированные задачи:
<code>/task Срочно: подготовить отчёт к пятнице, исполнитель Анна</code>

<b>3) Сводка за день</b>
<code>/summary Сегодня закрыли 2 тикета, ждём апрув от юристов</code>

<b>Также можно просто:</b>
• написать обычным текстом — я сам выберу агента
• отправить голосовое — распознаю и обработаю
• прислать файл — проиндексирую в базу знаний

🔒 Чувствительные данные идут только через локальный Ollama (on-prem).
"""

HELP_EN = """\
🤖 <b>What I can do</b>

I'm an enterprise multi-agent bot. Pick a flow:

<b>1) Document Q&amp;A (RAG)</b>
Upload .pdf / .txt / .docx, then ask:
<code>/ask What is the leave policy?</code>

<b>2) Task extraction</b>
Send text or voice — I return structured tasks:
<code>/task Urgent: prepare the report by Friday, assignee Anna</code>

<b>3) Daily summary</b>
<code>/summary Closed 2 tickets today, waiting on legal approval</code>

<b>You can also:</b>
• send plain text — I auto-route to an agent
• send a voice note — I transcribe and process it
• upload a file — I index it into the knowledge base

🔒 Sensitive requests stay on-prem via local Ollama.
"""

START_RU = """\
Привет! Я <b>Multi-Agent Bot</b> для рабочих задач.

<b>Коротко:</b>
📄 отвечаю по вашим файлам
✅ вытаскиваю задачи из текста/голоса
📊 делаю краткие сводки

Нажмите кнопку ниже или сразу попробуйте:
<code>/ask ...</code> · <code>/task ...</code> · <code>/summary ...</code>
"""

START_EN = """\
Hi! I'm a <b>Multi-Agent Bot</b> for work automation.

<b>In short:</b>
📄 answer questions from your files
✅ extract tasks from text/voice
📊 make short daily summaries

Tap a button below or try:
<code>/ask ...</code> · <code>/task ...</code> · <code>/summary ...</code>
"""

GUIDE_ASK_RU = """\
📄 <b>Спросить по файлу</b>

1) Пришлите документ (.pdf / .txt / .docx)
2) Задайте вопрос командой:
<code>/ask О чём этот документ?</code>

Или просто напишите вопрос после загрузки файла.
"""

GUIDE_ASK_EN = """\
📄 <b>Ask a document</b>

1) Send a file (.pdf / .txt / .docx)
2) Ask with:
<code>/ask What is this document about?</code>

Or just type a question after uploading.
"""

GUIDE_TASK_RU = """\
✅ <b>Извлечь задачи</b>

Напишите так:
<code>/task Подготовить презентацию к пятнице, исполнитель: Иван, срочно</code>

Или просто опишите задачу обычным текстом / голосом — я разберу на action item, priority, assignee, deadline.
"""

GUIDE_TASK_EN = """\
✅ <b>Extract tasks</b>

Try:
<code>/task Prepare the deck by Friday, assignee: Ivan, urgent</code>

Or just describe the task in plain text / voice — I'll parse action item, priority, assignee, deadline.
"""

GUIDE_SUMMARY_RU = """\
📊 <b>Сделать сводку</b>

Пример:
<code>/summary Утром созвон с клиентом, днём закрыли баг, вечером ждём ревью</code>

Я верну headline, пункты, действия и риски.
"""

GUIDE_SUMMARY_EN = """\
📊 <b>Make a summary</b>

Example:
<code>/summary Morning client call, fixed a bug at noon, waiting on review</code>

I'll return a headline, bullets, actions, and risks.
"""

GUIDE_UPLOAD_RU = """\
📎 <b>Как загрузить файл</b>

Просто отправьте сюда файл:
• .pdf
• .txt
• .docx

После индексации спросите через <code>/ask ...</code>
Документы хранятся отдельно по чату / вашим личным файлам.
"""

GUIDE_UPLOAD_EN = """\
📎 <b>How to upload</b>

Just send a file here:
• .pdf
• .txt
• .docx

After indexing, ask with <code>/ask ...</code>
Docs are scoped per chat / your personal library.
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
    text = START_RU if lang.startswith("ru") else START_EN
    await message.answer(text, reply_markup=main_menu_keyboard(lang=lang))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    lang = _lang_from_message(message)
    await message.answer(
        HELP_RU if lang.startswith("ru") else HELP_EN,
        reply_markup=main_menu_keyboard(lang=lang),
    )


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
        if lang.startswith("ru"):
            await message.answer(
                f"✅ Документ «{saved.filename}» проиндексирован.\n"
                f"Теперь спросите, например:\n"
                f"<code>/ask О чём документ {saved.filename}?</code>"
            )
        else:
            await message.answer(
                f"✅ Indexed «{saved.filename}».\n"
                f"Now ask, e.g.\n"
                f"<code>/ask What is {saved.filename} about?</code>"
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
    """Auto-route plain text; menu buttons show guided tips."""
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    lang = _lang_from_message(message, text)
    ru = lang.startswith("ru")

    menu_guides = {
        "❓ Что умею": HELP_RU,
        "❓ What I can do": HELP_EN,
        "❓ Справка": HELP_RU,
        "❓ Help": HELP_EN,
        "📄 Спросить по файлу": GUIDE_ASK_RU,
        "📄 Ask document": GUIDE_ASK_EN,
        "📄 RAG /ask": GUIDE_ASK_RU if ru else GUIDE_ASK_EN,
        "✅ Извлечь задачи": GUIDE_TASK_RU,
        "✅ Extract tasks": GUIDE_TASK_EN,
        "✅ Задачи /task": GUIDE_TASK_RU if ru else GUIDE_TASK_EN,
        "📊 Сделать сводку": GUIDE_SUMMARY_RU,
        "📊 Make summary": GUIDE_SUMMARY_EN,
        "📊 Сводка /summary": GUIDE_SUMMARY_RU if ru else GUIDE_SUMMARY_EN,
        "📎 Как загрузить файл": GUIDE_UPLOAD_RU,
        "📎 How to upload": GUIDE_UPLOAD_EN,
    }
    if text in menu_guides:
        await message.answer(menu_guides[text], reply_markup=main_menu_keyboard(lang=lang))
        return

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
