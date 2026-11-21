"""Application configuration and environment settings."""

import json
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Hostel Management System"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "development"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hostel_db"

    SECRET_KEY: str = "insecure-dev-secret-key-change-in-production"  # noqa: S105
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    CORS_ORIGINS: list[str] = ["*"]
    LOG_LEVEL: str = "INFO"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins from a comma-separated string, JSON string, or list."""
        if isinstance(v, str):
            if v.strip().startswith("["):
                try:
                    loaded = json.loads(v)
                    if isinstance(loaded, list):
                        return [str(item) for item in loaded]
                except (json.JSONDecodeError, TypeError):
                    return [i.strip() for i in v.split(",") if i.strip()]
            return [i.strip() for i in v.split(",") if i.strip()]
        if isinstance(v, list):
            return [str(item) for item in v]
        return ["*"]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()


settings: Settings = get_settings()
