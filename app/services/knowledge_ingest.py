"""Ingest files from a local knowledge/ folder into the global company KB."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.constants import GLOBAL_KB_CHAT_ID, GLOBAL_KB_OWNER_ID
from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.services.document_loader import SUPPORTED_EXTENSIONS, load_document_text
from app.services.vector_store import VectorStore

logger = get_logger(__name__)


async def ingest_knowledge_dir(
    knowledge_dir: str | Path | None = None,
    *,
    settings: Settings | None = None,
    replace_existing: bool = True,
) -> dict[str, int]:
    """
    Load all supported files from knowledge_dir into the global KB (chat_id=0).

    Returns counts: {"indexed": N, "skipped": N, "failed": N}
    """
    settings = settings or get_settings()
    root = Path(knowledge_dir or settings.knowledge_dir)
    stats = {"indexed": 0, "skipped": 0, "failed": 0}

    if not root.exists() or not root.is_dir():
        logger.warning("knowledge_dir_missing", path=str(root))
        return stats

    files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and not p.name.lower().startswith("readme")
    )
    if not files:
        logger.info("knowledge_dir_empty", path=str(root))
        return stats

    factory = get_session_factory()
    async with factory() as session:
        store = VectorStore(session)
        for path in files:
            try:
                text = await load_document_text(path)
                if not text.strip():
                    stats["skipped"] += 1
                    continue
                if replace_existing:
                    await store.delete_by_filename(
                        filename=path.name,
                        chat_id=GLOBAL_KB_CHAT_ID,
                        owner_user_id=GLOBAL_KB_OWNER_ID,
                    )
                await store.add_document(
                    filename=path.name,
                    content_type="text/plain",
                    text_content=text,
                    owner_user_id=GLOBAL_KB_OWNER_ID,
                    chat_id=GLOBAL_KB_CHAT_ID,
                    storage_path=str(path),
                )
                stats["indexed"] += 1
                logger.info("knowledge_doc_indexed", filename=path.name)
            except Exception as exc:
                stats["failed"] += 1
                logger.exception("knowledge_doc_failed", filename=path.name, error=str(exc))
        await session.commit()

    logger.info("knowledge_ingest_done", **stats, path=str(root))
    return stats
