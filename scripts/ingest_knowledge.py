"""CLI: ingest ./knowledge into the global company knowledge base."""

from __future__ import annotations

import asyncio
import sys

from app.core.config import get_settings
from app.core.database import dispose_db, init_db
from app.core.logging import setup_logging
from app.services.knowledge_ingest import ingest_knowledge_dir


async def main() -> int:
    settings = get_settings()
    setup_logging(debug=settings.debug)
    await init_db()
    stats = await ingest_knowledge_dir(settings.knowledge_dir, settings=settings)
    await dispose_db()
    print(f"Knowledge ingest complete: {stats}")
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
