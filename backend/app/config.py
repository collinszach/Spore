"""Spore backend configuration.

Reads from environment via pydantic-settings. All fields have dev-friendly
defaults so the app (and /health) boots even when env vars are unset —
later stories (1.2+) will rely on DATABASE_URL / REDIS_URL being correct.
"""

from pathlib import Path

from pydantic import field_validator
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

    # Embeddings provider selection: "ollama" (local, free), "voyage" (real,
    # paid), or "fake" (deterministic, default — tests / no-key local dev).
    embeddings_provider: str = "fake"
    ollama_url: str = "http://ollama:11434"

    # Epic 5 — Obsidian vault integration (CLAUDE.md rule 6: vault is sacred;
    # dev writes go to vault/_sandbox only). Empty string or "none" disables
    # vault writes entirely (NoOpVaultWriter).
    vault_path: str = str(_REPO_ROOT / "vault" / "_sandbox")
    vault_para_map: dict[str, str] = DEFAULT_VAULT_PARA_MAP

    # Epic 6 — Skills engine + Builder (CLAUDE.md rule 7: stronger model only
    # for build-out). `skills_dir` is scanned for `*.skill.yaml` files;
    # dropping a new file registers it with no code change (Story 6.1).
    # In the container, the PM mounts the repo's `skills/` dir at `/skills`
    # and sets SKILLS_DIR=/skills.
    skills_dir: str = str(_REPO_ROOT / "skills")
    builder_model: str = "claude-sonnet-4-6"

    # Epic 7 — Idea pipeline & state machine (Stories 7.3 / 7.4).
    # promote_ref_count: minimum incoming note_link references before a note
    # is "promotion-ready" (suggest its next forward idea_state).
    # stale_days: how long a 'seedling' can sit untouched before it's flagged
    # as stale in GET /pipeline/suggestions and POST /internal/stale-sweep.
    promote_ref_count: int = 3
    stale_days: int = 14

    # Epic 8 — Resurfacing & reminders (Curator).
    # curator_model: cheap model for the optional one-line digest narrative
    # (CLAUDE.md rule 7: cost discipline — Curator default = $0).
    # curator_narrative_enabled: gate for the narrative LLM call; off by
    # default so digests are pure structured aggregation (no skill_run cost).
    # resurface_schedule_days: whole-days-since-creation buckets at which a
    # note is "due to resurface" (FR31). CSV via RESURFACE_SCHEDULE_DAYS.
    curator_model: str = "claude-haiku-4-5-20251001"
    curator_narrative_enabled: bool = False
    resurface_schedule_days: list[int] = [1, 3, 7, 30]

    # Epic 9 — Feedback loop (Story 9.2 / FR37). When enabled, the Sorter
    # prompt appends a short few-shot block built from the K most recent
    # `correction` rows (original_json -> corrected_json), to nudge future
    # triage toward user-corrected routing. Default False — keeps existing
    # Sorter/triage tests deterministic and $0 (no extra prompt content).
    sorter_fewshot_enabled: bool = False
    sorter_fewshot_k: int = 5

    # Story 2.6 — Voice capture transcription (ADR-001: local Whisper).
    # transcription_provider: "whisper" (real, local ASR service) or "fake"
    # (default — deterministic, tests / no-whisper local dev).
    transcription_provider: str = "fake"
    whisper_url: str = "http://whisper:9000"
    media_dir: str = "/media"

    # Epic 8 — APNs push delivery (Story 1.4 device-auth wiring). Disabled by
    # default so existing tests/dev keep NoOpNotifier with zero config.
    # apns_key_path: path to the .p8 ES256 private key (NOT committed; PM
    # mounts /secrets into the api container). apns_use_sandbox=True targets
    # api.sandbox.push.apple.com (dev/TestFlight builds); set False for prod.
    apns_enabled: bool = False
    apns_key_path: str = "/secrets/AuthKey_T7GUUS93Q3.p8"
    apns_key_id: str = "T7GUUS93Q3"
    apns_team_id: str = ""
    apns_topic: str = "com.spore.app"
    apns_use_sandbox: bool = True

    @field_validator("resurface_schedule_days", mode="before")
    @classmethod
    def _parse_resurface_schedule_days(cls, value):
        """Allow `RESURFACE_SCHEDULE_DAYS=1,3,7,30` (comma-separated) from env."""
        if isinstance(value, str):
            return [int(v.strip()) for v in value.split(",") if v.strip()]
        return value


settings = Settings()
