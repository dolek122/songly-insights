"""Application settings read from environment variables (and the optional .env file)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://songly:songly@localhost:5432/insights"
    test_database_url: str = "postgresql+psycopg://songly:songly@localhost:5432/insights_test"
    # Sent in the User-Agent to MusicBrainz and ListenBrainz, which ask for a way to contact
    # the author (an e-mail or a project URL). Optional, but please set it before real imports.
    musicbrainz_contact: str | None = None
    # "json" = one JSON object per log line (Docker deployment, ADR 0018). "text" leaves
    # Python's and uvicorn's default logging untouched (local development, tests).
    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    # Cached so the .env file is read only once per process.
    return Settings()
