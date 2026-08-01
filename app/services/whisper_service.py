"""Voice transcription: local faster-whisper with API fallback."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.mock_providers import mock_transcribe

logger = get_logger(__name__)

_whisper_model = None


class WhisperService:
    """Transcribe Telegram voice messages."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe an audio file to text."""
        path = Path(file_path)
        mode = self.settings.whisper_mode

        if mode == "mock" or (mode == "auto" and self.settings.use_mocks and not self.settings.openai_api_key):
            # Try local first in auto when possible; fall back to mock
            try:
                if mode != "mock":
                    return await self._local_transcribe(path)
            except Exception as exc:
                logger.warning("whisper_local_failed", error=str(exc))
                return mock_transcribe(path.name)
            return mock_transcribe(path.name)

        if mode == "local":
            return await self._local_transcribe(path)

        if mode == "api":
            return await self._api_transcribe(path)

        # auto: local → api → mock
        try:
            return await self._local_transcribe(path)
        except Exception as local_exc:
            logger.warning("whisper_local_failed", error=str(local_exc))
            try:
                return await self._api_transcribe(path)
            except Exception as api_exc:
                logger.warning("whisper_api_failed", error=str(api_exc))
                if self.settings.use_mocks:
                    return mock_transcribe(path.name)
                raise

    async def _local_transcribe(self, path: Path) -> str:
        global _whisper_model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed") from exc

        if _whisper_model is None:
            _whisper_model = WhisperModel(self.settings.whisper_model_size, device="cpu", compute_type="int8")

        segments, _info = _whisper_model.transcribe(str(path), beam_size=1)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if not text:
            raise ValueError("Empty transcription from local Whisper")
        return text

    async def _api_transcribe(self, path: Path) -> str:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY required for Whisper API fallback")

        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
        )
        with path.open("rb") as audio:
            result = await client.audio.transcriptions.create(model="whisper-1", file=audio)
        text = (result.text or "").strip()
        if not text:
            raise ValueError("Empty transcription from Whisper API")
        return text
