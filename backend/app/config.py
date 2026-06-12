"""Spore backend configuration.

Reads from environment via pydantic-settings. All fields have dev-friendly
defaults so the app (and /health) boots even when env vars are unset —
later stories (1.2+) will rely on DATABASE_URL / REDIS_URL being correct.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://spore:spore@localhost:5432/spore"
    redis_url: str = "redis://localhost:6379/0"
    spore_capture_token: str = "dev-token"


settings = Settings()
