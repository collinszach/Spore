-- Spore — 001_init.sql
-- Canonical schema. pgvector + TimescaleDB. Embedding dim = 1024 (voyage-3-lite; see ADR-002).
-- HARD STOP: never auto-apply. Reviewed migrations only.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ── Capture ──────────────────────────────────────────────────────────────
CREATE TABLE raw_capture (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source       TEXT NOT NULL,                 -- ios_quick | share_sheet | siri | widget | voice | email | telegram
    body         TEXT,
    media_url    TEXT,
    transcribed  BOOLEAN NOT NULL DEFAULT FALSE,
    lang         TEXT,
    status       TEXT NOT NULL DEFAULT 'pending', -- pending | triaged | failed
    device_id    UUID,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);
SELECT create_hypertable('raw_capture', 'created_at', if_not_exists => TRUE);
CREATE INDEX idx_capture_status ON raw_capture (status, created_at);

-- ── Notes (machine mirror of vault prose) ────────────────────────────────
CREATE TABLE note (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vault_path       TEXT UNIQUE,
    title            TEXT,
    type             TEXT,                       -- fleeting | project_idea | task | reference | question | journal
    domain           TEXT,
    tags             TEXT[] DEFAULT '{}',
    idea_state       TEXT DEFAULT 'seedling',    -- seedling | sapling | sprout | project | shipped | archived
    confidence       REAL,
    embedding        VECTOR(1024),
    source_capture_id UUID REFERENCES raw_capture(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_note_state  ON note (idea_state);
CREATE INDEX idx_note_domain ON note (domain);
-- ANN index; tune lists after data lands (or switch to HNSW)
CREATE INDEX idx_note_embedding ON note USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE note_link (
    src_id  UUID REFERENCES note(id) ON DELETE CASCADE,
    dst_id  UUID REFERENCES note(id) ON DELETE CASCADE,
    kind    TEXT NOT NULL DEFAULT 'related',     -- related | parent | derived | duplicate
    PRIMARY KEY (src_id, dst_id, kind)
);

-- ── Pipeline state-machine audit ─────────────────────────────────────────
CREATE TABLE idea_event (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    note_id    UUID REFERENCES note(id) ON DELETE CASCADE,
    from_state TEXT,
    to_state   TEXT NOT NULL,
    reason     TEXT,                             -- manual | rule:ref_count | rule:stale | skill
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Review queue ─────────────────────────────────────────────────────────
CREATE TABLE review_item (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    capture_id     UUID REFERENCES raw_capture(id),
    reason         TEXT,                          -- low_confidence | duplicate | ambiguous
    status         TEXT NOT NULL DEFAULT 'open',  -- open | approved | redirected | merged | discarded
    suggested_path TEXT,
    suggested_type TEXT,
    confidence     REAL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at    TIMESTAMPTZ
);
CREATE INDEX idx_review_open ON review_item (status) WHERE status = 'open';

CREATE TABLE correction (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    review_item_id UUID REFERENCES review_item(id),
    original_json  JSONB,
    corrected_json JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Reminders & resurfacing ──────────────────────────────────────────────
CREATE TABLE reminder (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    note_id    UUID REFERENCES note(id) ON DELETE CASCADE,
    fire_at    TIMESTAMPTZ NOT NULL,
    channel    TEXT NOT NULL DEFAULT 'apns',      -- apns | telegram | ntfy
    recurrence TEXT,                              -- null | daily | weekly | spaced
    status     TEXT NOT NULL DEFAULT 'scheduled', -- scheduled | fired | cancelled
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_reminder_due ON reminder (fire_at) WHERE status = 'scheduled';

-- ── Skill runs (cost ledger) ─────────────────────────────────────────────
CREATE TABLE skill_run (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    skill       TEXT NOT NULL,
    note_id     UUID REFERENCES note(id),
    status      TEXT NOT NULL DEFAULT 'ok',
    output_path TEXT,
    model       TEXT,
    tokens_in   INT,
    tokens_out  INT,
    cost_usd    NUMERIC(10,5),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_skillrun_cost ON skill_run (created_at);

-- ── Devices (APNs) ───────────────────────────────────────────────────────
CREATE TABLE device (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    apns_token  TEXT UNIQUE,
    platform    TEXT NOT NULL DEFAULT 'ios',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ
);
