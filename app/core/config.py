"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the multi-agent Telegram bot service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Multi-Agent Telegram Bot"
    app_env: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    use_mocks: bool = True

    api_keys: str = Field(default="change-me-in-production")

    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""
    telegram_webhook_secret: str = ""
    telegram_mode: Literal["polling", "webhook"] = "polling"
    allowed_user_ids: str = ""
    allowed_chat_ids: str = ""

    max_text_length: int = 50_000
    max_upload_bytes: int = 20 * 1024 * 1024
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60

    database_url: str = "postgresql+asyncpg://bot:bot@localhost:5432/multi_agent_bot"
    redis_url: str = "redis://localhost:6379/0"

    llm_provider: Literal["auto", "ollama", "gemini", "mock"] = "auto"
    llm_max_retries: int = 3
    llm_temperature: float = 0.1
    sensitive_keywords: str = (
        "confidential,secret,пароль,password,персональн,pii,internal only,строго конфиденциально"
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3"
    ollama_embed_model: str = "nomic-embed-text"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    embedding_dimensions: int = 768
    chunk_size: int = 800
    chunk_overlap: int = 120
    rag_top_k: int = 5
    min_confidence_threshold: float = 0.35

    whisper_mode: Literal["local", "api", "auto", "mock"] = "auto"
    whisper_model_size: str = "base"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    upload_dir: str = "./uploads"

    @field_validator("api_keys", mode="before")
    @classmethod
    def _normalize_api_keys(cls, value: object) -> str:
        if value is None:
            return "change-me-in-production"
        return str(value)

    @property
    def api_key_set(self) -> set[str]:
        return {key.strip() for key in self.api_keys.split(",") if key.strip()}

    @property
    def allowed_user_id_set(self) -> set[int]:
        return {int(x.strip()) for x in self.allowed_user_ids.split(",") if x.strip().isdigit()}

    @property
    def allowed_chat_id_set(self) -> set[int]:
        result: set[int] = set()
        for part in self.allowed_chat_ids.split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                result.add(int(part))
        return result

    @property
    def sensitive_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.sensitive_keywords.split(",") if k.strip()]

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
