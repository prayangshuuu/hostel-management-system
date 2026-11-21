"""Application configuration and environment settings."""

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


settings = Settings()
