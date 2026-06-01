# ============================================================
# Yuno Agent Platform — Configuration Management
# Uses pydantic-settings for type-safe config with .env support
# ============================================================
from __future__ import annotations

import json
from functools import lru_cache
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables / .env file.
    Using pydantic-settings ensures:
    - Type safety
    - Required field validation on startup
    - Clear configuration documentation
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application ----------------------------------------
    app_name: str = "Yuno Agent Platform"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    secret_key: str = "dev-secret-key-change-in-production-32chars"
    api_prefix: str = "/api"
    version: str = "1.0.0"

    # ---- Database -------------------------------------------
    database_url: str = (
        "postgresql+asyncpg://yuno:yuno_password@localhost:5432/yuno_agents"
    )
    database_url_sync: str = (
        "postgresql://yuno:yuno_password@localhost:5432/yuno_agents"
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout: int = 30
    log_sql_queries: bool = False

    # ---- Redis ----------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_name: str = "agent_jobs"
    redis_result_ttl: int = 3600  # 1 hour

    # ---- OpenAI ---------------------------------------------
    openai_api_key: str = "sk-placeholder"
    openai_default_model: str = "gpt-4o-mini"
    openai_fallback_model: str = "gpt-3.5-turbo"

    # ---- Telegram -------------------------------------------
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = "dev-webhook-secret"
    telegram_webhook_url: str = ""

    # ---- LangGraph ------------------------------------------
    langgraph_checkpoint_table: str = "langgraph_checkpoints"
    langgraph_max_iterations: int = 10
    langgraph_timeout_seconds: int = 120

    # ---- Cost Controls --------------------------------------
    max_cost_per_execution: float = 0.50
    max_tokens_per_execution: int = 50000

    # ---- CORS -----------------------------------------------
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

    # ---- Observability --------------------------------------
    enable_metrics: bool = True

    # ---- Demo Mode ------------------------------------------
    demo_mode: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | List[str]) -> List[str]:
        """Parse CORS origins from JSON string or list."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [origin.strip() for origin in v.split(",")]
        return v

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Enforce security requirements in production."""
        if self.app_env == "production":
            if self.secret_key == "dev-secret-key-change-in-production-32chars":
                raise ValueError("SECRET_KEY must be changed in production")
            if len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters")
            if not self.openai_api_key.startswith("sk-"):
                raise ValueError("OPENAI_API_KEY is required in production")
        return self

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def has_telegram(self) -> bool:
        """Check if Telegram integration is configured."""
        return bool(self.telegram_bot_token and self.telegram_bot_token != "")

    @property
    def has_openai(self) -> bool:
        """Check if OpenAI is properly configured."""
        return self.openai_api_key.startswith("sk-") and len(self.openai_api_key) > 10


@lru_cache()
def get_settings() -> Settings:
    """
    Cached settings instance.
    Using lru_cache ensures single Settings object per process.
    Call get_settings() anywhere in the application.
    """
    return Settings()


# Module-level convenience accessor
settings = get_settings()
