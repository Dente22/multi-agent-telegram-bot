"""Helpers for relative deadline parsing (RU/EN weekday phrases)."""

from __future__ import annotations

import re
from datetime import date, timedelta


_WEEKDAYS_RU = {
    "понедельник": 0,
    "вторник": 1,
    "среду": 2,
    "среда": 2,
    "четверг": 3,
    "пятницу": 4,
    "пятница": 4,
    "субботу": 5,
    "суббота": 5,
    "воскресенье": 6,
}

_WEEKDAYS_EN = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def next_weekday(target: int, *, today: date | None = None) -> date:
    """Return the next date matching weekday (0=Mon .. 6=Sun), not in the past."""
    today = today or date.today()
    days_ahead = (target - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def infer_deadline_from_text(text: str, *, today: date | None = None) -> date | None:
    """Best-effort relative deadline from free text."""
    today = today or date.today()
    lowered = text.lower()

    if re.search(r"\bсегодня\b|\btoday\b", lowered):
        return today
    if re.search(r"\bзавтра\b|\btomorrow\b", lowered):
        return today + timedelta(days=1)
    if re.search(r"\bпослезавтра\b", lowered):
        return today + timedelta(days=2)

    for name, weekday in {**_WEEKDAYS_RU, **_WEEKDAYS_EN}.items():
        if name in lowered:
            return next_weekday(weekday, today=today)
    return None


def normalize_deadline(deadline: date | None, source_text: str) -> date | None:
    """
    Fix hallucinated past deadlines using relative phrases from the source text.
    If LLM returned a past date, prefer inferred relative date.
    """
    inferred = infer_deadline_from_text(source_text)
    today = date.today()

    if deadline is None:
        return inferred
    if deadline < today:
        return inferred or deadline
    return deadline
