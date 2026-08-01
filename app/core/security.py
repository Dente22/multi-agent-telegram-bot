"""Input/output sanitization and sensitive-data detection."""

from __future__ import annotations

import re

from app.core.config import get_settings

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
        r"disregard\s+(all\s+)?(previous|prior|above)",
        r"you\s+are\s+now\s+(dan|unfiltered|jailbroken)",
        r"system\s*prompt\s*:",
        r"<\s*/?\s*system\s*>",
        r"\[\s*INST\s*\]",
        r"do\s+not\s+follow\s+your\s+(system|developer)\s+prompt",
        r"reveal\s+(your|the)\s+(system|hidden)\s+prompt",
        r"игнорируй\s+(все\s+)?(предыдущие|прошлые)\s+инструкции",
        r"забудь\s+(все\s+)?правила",
    )
)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SECRET_LEAK = re.compile(
    r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}"
)


class SanitizationError(ValueError):
    """Raised when input fails security validation."""


def sanitize_user_text(text: str, *, field_name: str = "text", max_length: int | None = None) -> str:
    """Normalize and harden user-supplied text against prompt injection."""
    settings = get_settings()
    limit = max_length or settings.max_text_length
    cleaned = _CONTROL_CHARS.sub("", text).strip()
    if not cleaned:
        raise SanitizationError(f"{field_name} must not be empty after sanitization")
    if len(cleaned) > limit:
        raise SanitizationError(f"{field_name} exceeds max length ({limit})")

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(cleaned):
            raise SanitizationError(
                f"{field_name} rejected: potential prompt-injection pattern detected"
            )
    return cleaned


def sanitize_output(text: str) -> str:
    """Strip accidental secret-like payloads from model output."""
    return _SECRET_LEAK.sub("[REDACTED]", text)


def is_sensitive_request(text: str) -> bool:
    """Detect requests that must stay on-premise (Ollama only)."""
    lowered = text.lower()
    return any(keyword in lowered for keyword in get_settings().sensitive_keyword_list)
