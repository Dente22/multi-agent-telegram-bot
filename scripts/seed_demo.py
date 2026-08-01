"""Seed a demo document for local demos."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.database import get_session_factory, init_db
from app.services.vector_store import VectorStore

DEMO_TEXT = """
Corporate Leave Policy (Demo)
Employees must request leave at least 5 business days in advance.
Manager approval is required within 48 hours.
Confidential personnel data must stay on-premise.
"""


async def main() -> None:
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        store = VectorStore(session)
        doc = await store.add_document(
            filename="demo-policy.txt",
            content_type="text/plain",
            text_content=DEMO_TEXT,
            owner_user_id=1,
            chat_id=1,
            storage_path=None,
        )
        await session.commit()
        print(f"Seeded document id={doc.id}")

    Path("uploads").mkdir(exist_ok=True)
    Path("uploads/demo-policy.txt").write_text(DEMO_TEXT, encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
