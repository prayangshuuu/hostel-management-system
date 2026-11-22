"""Application configuration and environment settings."""

import json
from functools import lru_cache
from typing import Any, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Hostel Management System"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hostel_db"

    SECRET_KEY: str = "insecure-dev-secret-key-change-in-production"  # noqa: S105
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    CORS_ORIGINS: list[str] = ["*"]
    LOG_LEVEL: str = "INFO"

    VISIT_START: str = "08:00"
    VISIT_END: str = "20:00"

    MEAL_OPTOUT_CUTOFF_HOURS: int = 12

    # Security & Lockout
    FAILED_LOGIN_LIMIT: int = 5
    LOCKOUT_DURATION_MINUTES: int = 15
    ENABLE_DOCS: bool = False
    MAX_REQUEST_BODY_SIZE: int = 5 * 1024 * 1024  # 5MB

    # Database Pool Settings
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_PRE_PING: bool = True

    @model_validator(mode="after")
    def validate_production_secret_key(self) -> Self:
        """Validate SECRET_KEY strength and safety when running in production environment."""
        if self.APP_ENV == "production":
            lowered = self.SECRET_KEY.lower()
            if (
                len(self.SECRET_KEY) < 32
                or "insecure" in lowered
                or "dev-secret" in lowered
                or self.SECRET_KEY == "insecure-dev-secret-key-change-in-production"  # noqa: S105 # nosec B105 # nosec B105
            ):
                raise ValueError(
                    "In production, SECRET_KEY must be at least 32 characters long "
                    "and cannot contain 'insecure', 'dev-secret', or default values."
                )
        return self

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
