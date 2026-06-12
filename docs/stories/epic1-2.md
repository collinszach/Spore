# Spore — Sharded Stories: Epic 1 & 2 (docs/stories/)

> BMAD V6 sharding. One story = one mergeable PR. AC copied verbatim from PRD. Pick top-to-bottom.

---

## Epic 1 — Backend Spine & Foundations

### Story 1.1 — Stand up the stack
**As a** developer, **I want** the full local stack running, **so that** every later story has infra.
**AC:** `docker compose up` boots all services; healthchecks pass; `001_init.sql` applied with pgvector + Timescale enabled.
**Constraints:** use provided `docker-compose.yml` + `001_init.sql`. API on :8020 (avoid KoastCast 8010/8011). HARD STOP before editing migrations.
**Tests:** `pytest backend/tests/test_health.py` (GET /health → 200); `psql` confirms `vector` + `timescaledb` extensions.
**Agent:** backend-engineer · **Deps:** none.

### Story 1.2 — Data layer + repositories
**As a** developer, **I want** typed repositories over the schema, **so that** services never write raw SQL in routers.
**AC:** repository modules for capture/note/review/reminder/skill_run with CRUD + the pgvector kNN query; migrations verified.
**Tests:** repo unit tests against the test DB; kNN returns ordered neighbors.
**Agent:** backend-engineer · **Deps:** 1.1.

### Story 1.3 — `/capture` endpoint
**As a** capture surface, **I want** an authed idempotent capture endpoint, **so that** thoughts land reliably.
**AC:** valid request creates `raw_capture` (→201); invalid token →401; duplicate `capture_uuid` is idempotent (no dupe).
**Constraints:** router→service→repo; `{ok,data,error}` envelope; token dependency.
**Tests:** contract test — happy path, auth failure, bad input, retry-idempotency.
**Agent:** backend-engineer · **Deps:** 1.2.

### Story 1.4 — Cloudflare Tunnel + device auth
**As an** operator, **I want** external reach with no open ports, **so that** the NUC stays closed.
**AC:** endpoint reachable via tunnel; no inbound ports; `POST /devices` registers an APNs token.
**Tests:** integration hit through tunnel URL; device row created.
**Agent:** backend-engineer · **Deps:** 1.3 · **Note:** needs your TUNNEL_TOKEN in `.env`.

### Story 1.5 — Telegram fallback capture
**As a** user, **I want** to capture via Telegram before the app exists, **so that** I can validate triage early (ADR-005).
**AC:** text and voice Telegram messages create captures; voice flagged for transcription.
**Tests:** n8n flow posts to `/capture`; capture rows created with correct source.
**Agent:** backend-engineer · **Deps:** 1.3.

---

## Epic 2 — iOS App Shell & Capture Surfaces

### Story 2.1 — App shell + tabs
**As a** user, **I want** the app to open ready to capture, **so that** there's zero friction.
**AC:** app launches to Capture with keyboard focused; tabs present (Capture/Review/Pipeline/Notes/Today).
**Tests:** XCTest UI smoke; ViewModel unit test.
**Agent:** ios-engineer (skill: swiftui-screen) · **Deps:** none.

### Story 2.2 — Quick capture + offline queue
**As a** user, **I want** captures to save instantly even offline, **so that** no thought is lost (NFR1/NFR6).
**AC:** saves locally <500ms; syncs to `/capture` when online; survives airplane mode; idempotent via `capture_uuid`.
**Constraints:** SwiftData `CaptureQueue`; retry with backoff; no keys in binary.
**Tests:** queue unit tests (offline→online drain, dedupe on retry).
**Agent:** ios-engineer · **Deps:** 2.1, 1.3.

### Story 2.3 — Share Sheet extension
**AC:** sharing text/URL/image from any app creates a capture with source metadata.
**Tests:** extension target unit test; payload mapping verified.
**Agent:** ios-engineer · **Deps:** 2.2.

### Story 2.4 — App Intents + Siri
**AC:** "Note to Spore" dictation creates a capture hands-free.
**Tests:** intent unit test; capture created from intent payload.
**Agent:** ios-engineer · **Deps:** 2.2.

### Story 2.5 — Widget + Control Center + back-tap
**AC:** each entry point opens capture or one-shot dictation.
**Tests:** widget snapshot test; deep-link routing test.
**Agent:** ios-engineer · **Deps:** 2.2.

### Story 2.6 — Voice capture + transcription
**AC:** recording produces a transcribed capture; audio retained and linked. (Transcription path per ADR-001.)
**Tests:** record→upload→transcribe integration (mock Whisper); capture has transcript + media_url.
**Agent:** ios-engineer + backend-engineer · **Deps:** 2.2, 1.3 · **Decision needed:** ADR-001 (API vs local Whisper) before build.

---

### Suggested merge order
1.1 → 1.2 → 1.3 → (1.4, 1.5 parallel) → 2.1 → 2.2 → (2.3, 2.4, 2.5 parallel) → 2.6.
Run `/ship` (qa-reviewer) before each merge.
