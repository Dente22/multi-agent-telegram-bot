"""Offline mock providers for demo mode without API keys."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta


def mock_chat_completion(*, system: str, user: str, json_mode: bool) -> str:
    """Deterministic mock LLM used when USE_MOCKS=true / providers offline."""
    lowered = (system + "\n" + user).lower()

    if json_mode and ("task" in lowered or "action_item" in lowered or "extract" in lowered):
        deadline = (date.today() + timedelta(days=3)).isoformat()
        # Prefer relative weekday if mentioned
        from app.services.dates import infer_deadline_from_text

        inferred = infer_deadline_from_text(user)
        if inferred:
            deadline = inferred.isoformat()
        payload = {
            "tasks": [
                {
                    "action_item": _extract_action(user),
                    "priority": "high" if any(w in user.lower() for w in ("urgent", "срочно", "asap")) else "medium",
                    "assignee": _extract_assignee(user),
                    "deadline": deadline,
                    "notes": "Extracted in mock mode",
                }
            ],
            "source_language": "ru" if re.search(r"[а-яА-Я]", user) else "en",
            "confidence": 0.82,
        }
        return json.dumps(payload, ensure_ascii=False)

    if json_mode and ("route" in lowered or "agent" in lowered):
        agent = "extractor"
        if any(w in lowered for w in ("document", "rag", "/ask", "файл", "pdf")):
            agent = "rag"
        elif any(w in lowered for w in ("summary", "итог", "сводк")):
            agent = "summary"
        return json.dumps(
            {
                "agent": agent,
                "reason": "Mock router heuristic",
                "sensitive": "confidential" in lowered or "конфиденц" in lowered,
                "confidence": 0.7,
            }
        )

    if json_mode and ("summary" in lowered or "headline" in lowered):
        return json.dumps(
            {
                "headline": "Daily ops digest (mock)",
                "bullet_points": [
                    "3 updates processed",
                    "2 action items pending",
                    "No critical blockers",
                ],
                "action_items": ["Follow up on open tasks"],
                "risks": [],
                "estimated_time_saved_pct": 30,
            },
            ensure_ascii=False,
        )

    if json_mode and ("answer" in lowered or "sources" in lowered or "rag" in lowered):
        return json.dumps(
            {
                "answer": "Based on available documents (mock), the policy requires manager approval within 48 hours.",
                "confidence_score": 0.75,
                "sources": [
                    {
                        "document_id": "1",
                        "chunk_id": "1",
                        "filename": "demo-policy.txt",
                        "excerpt": "Manager approval within 48 hours.",
                        "score": 0.88,
                        "page": 1,
                    }
                ],
            },
            ensure_ascii=False,
        )

    if json_mode:
        return "{}"

    return (
        "Mock assistant: I received your message. "
        "Configure Ollama / Gemini keys for live responses."
    )


def mock_embedding(text: str, dimensions: int = 768) -> list[float]:
    """Cheap deterministic pseudo-embedding for demo vector search."""
    vector = [0.0] * dimensions
    if not text:
        return vector
    for i, ch in enumerate(text.encode("utf-8")):
        vector[i % dimensions] += (ch / 255.0) * 0.01
    # L2 normalize
    norm = sum(v * v for v in vector) ** 0.5 or 1.0
    return [v / norm for v in vector]


def mock_transcribe(filename: str = "voice.ogg") -> str:
    """Mock transcription for voice messages."""
    return f"[mock transcript from {filename}] Please prepare the weekly report by Friday, assignee: Anna."


def _extract_action(user: str) -> str:
    lines = [ln.strip() for ln in user.splitlines() if ln.strip()]
    for line in lines:
        if line.lower().startswith("text:") or line.lower().startswith("message:"):
            return line.split(":", 1)[1].strip()[:500] or "Follow up on request"
    return (lines[-1] if lines else "Follow up on request")[:500]


def _extract_assignee(user: str) -> str | None:
    match = re.search(r"(?:assignee|исполнитель|для)\s*[:\-]?\s*@?([A-Za-zА-Яа-я0-9_\.]+)", user, re.I)
    return match.group(1) if match else None
