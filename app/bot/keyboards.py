"""Reply / inline keyboards."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_keyboard(*, lang: str = "ru") -> ReplyKeyboardMarkup:
    if lang.startswith("ru"):
        rows = [
            [KeyboardButton(text="❓ Справка"), KeyboardButton(text="📄 RAG /ask")],
            [KeyboardButton(text="✅ Задачи /task"), KeyboardButton(text="📊 Сводка /summary")],
        ]
    else:
        rows = [
            [KeyboardButton(text="❓ Help"), KeyboardButton(text="📄 RAG /ask")],
            [KeyboardButton(text="✅ Tasks /task"), KeyboardButton(text="📊 Summary /summary")],
        ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
