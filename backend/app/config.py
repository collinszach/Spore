"""Spore backend configuration.

Reads from environment via pydantic-settings. All fields have dev-friendly
defaults so the app (and /health) boots even when env vars are unset —
later stories (1.2+) will rely on DATABASE_URL / REDIS_URL being correct.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from backend/app/ (backend/app/config.py -> backend/ -> repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Default PARA folder mapping by note type (Epic 5, Story 5.1). Unknown
# types fall back to "00_Inbox". Overridable via Settings.vault_para_map.
DEFAULT_VAULT_PARA_MAP: dict[str, str] = {
    "project_idea": "20_Projects",
    "reference": "30_Resources",
    "task": "10_Areas",
    "journal": "10_Areas",
    "fleeting": "00_Inbox",
    "question": "00_Inbox",
}


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

    # Epic 5 — Obsidian vault integration (CLAUDE.md rule 6: vault is sacred;
    # dev writes go to vault/_sandbox only). Empty string or "none" disables
    # vault writes entirely (NoOpVaultWriter).
    vault_path: str = str(_REPO_ROOT / "vault" / "_sandbox")
    vault_para_map: dict[str, str] = DEFAULT_VAULT_PARA_MAP


settings = Settings()
