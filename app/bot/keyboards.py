"""Reply / inline keyboards."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_keyboard(*, lang: str = "ru") -> ReplyKeyboardMarkup:
    if lang.startswith("ru"):
        rows = [
            [KeyboardButton(text="📄 Спросить по файлу"), KeyboardButton(text="✅ Извлечь задачи")],
            [KeyboardButton(text="📊 Сделать сводку"), KeyboardButton(text="❓ Что умею")],
            [KeyboardButton(text="📎 Как загрузить файл")],
        ]
    else:
        rows = [
            [KeyboardButton(text="📄 Ask document"), KeyboardButton(text="✅ Extract tasks")],
            [KeyboardButton(text="📊 Make summary"), KeyboardButton(text="❓ What I can do")],
            [KeyboardButton(text="📎 How to upload")],
        ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
