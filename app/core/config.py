"""Application settings, loaded from environment variables / .env.

Nothing is hard-coded in the codebase: the same image runs locally and in Docker
purely by changing environment variables. See .env.example for the full list.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"

    # SQLAlchemy URL. Default targets a local Postgres (see docker-compose.yml).
    database_url: str = (
        "postgresql+psycopg://drivenow:drivenow@localhost:5432/drivenow"
    )

    # Message queue. Disabled by default so the app runs without a broker.
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    enable_message_queue: bool = False

    log_level: str = "INFO"
    log_file: str = "logs/app.log"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read env once per process)."""
    return Settings()
