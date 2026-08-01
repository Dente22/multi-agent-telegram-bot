"""Aiogram filters."""

from __future__ import annotations

from aiogram.filters import Filter
from aiogram.types import Message


class IsPrivateOrGroup(Filter):
    """Allow private chats and groups/supergroups."""

    async def __call__(self, message: Message) -> bool:
        return message.chat.type in {"private", "group", "supergroup"}
