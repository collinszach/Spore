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

    # Epic 3 — Sorter + embeddings + dedup
    sorter_model: str = "claude-haiku-4-5-20251001"
    embedding_model: str = "voyage-3-lite"
    direct_write_threshold: float = 0.80
    review_floor: float = 0.50
    dup_similarity_threshold: float = 0.90
    voyage_api_key: str = ""
    anthropic_api_key: str = ""
    triage_batch_limit: int = 25


settings = Settings()
