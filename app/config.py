from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://songly:songly@localhost:5432/insights"
    test_database_url: str = "postgresql+psycopg://songly:songly@localhost:5432/insights_test"
    musicbrainz_contact: str | None = None
    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
