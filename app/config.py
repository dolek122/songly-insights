"""Application settings read from environment variables (and the optional .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://songly:songly@localhost:5432/insights"
    test_database_url: str = "postgresql+psycopg://songly:songly@localhost:5432/insights_test"


@lru_cache
def get_settings() -> Settings:
    # Cached so the .env file is read only once per process.
    return Settings()
