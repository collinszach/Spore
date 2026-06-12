# Spore — STATUS

_Last updated: 2026-06-12. Update at the end of every session._

## Now
Repo scaffolded + pushed. **Story 1.1 DONE** — stack live on remote Docker host: db/redis/api
healthy, `/health` 200, schema + extensions applied. Next action: **Story 1.2 — data layer + repositories.**

## Infra notes
- Docker runs on remote host `zach@100.91.198.28` (Ubuntu, Docker 29.5 / Compose v5.1). Repo synced to `~/spore`; `.env` lives there (not committed).
- Shared host: dropped host port publishing for db/redis (internal-only, NFR4); api on :8020, n8n on :5678.
- cloudflared deferred to Story 1.4 (needs TUNNEL_TOKEN).
- Migration fix (approved): raw_capture is a plain table, not a hypertable — Timescale forbids the id-only PK + inbound FKs. See note in 001_init.sql.

## Done
- [x] SPEC.md / PRD.md / ARCHITECTURE.md / Build Kit
- [x] Stories sharded: Epic 1 + Epic 2
- [x] Repo scaffolded (.claude kit, docs/, infra) + pushed to GitHub
- [x] **Story 1.1** — stack stood up; /health 200; pgvector+Timescale; 9 tables

## Next 3 stories
1. **1.2** data layer + repositories (backend-engineer) — Deps: 1.1 ✓
2. **1.3** `/capture` endpoint (backend-engineer)
3. **2.1 → 2.2** iOS app shell + offline capture queue (ios-engineer)

## Open decisions (block specific stories)
- ADR-001 Whisper API vs local → blocks Story 2.6
- ADR-002 embeddings (voyage-3-lite 1024) → fixed in schema; change = reindex
- ADR-003 write threshold 0.80 vs 0.90 → tune from gate-distribution metric
- ADR-004 Obsidian Sync vs Syncthing → non-blocking (read sync only)

## Blockers
- Need `TUNNEL_TOKEN` (Cloudflare) in `.env` for Story 1.4
- Need APNs `.p8` key for push (Epic 8) — not yet

## Guardrails (do not relax)
- Vault writes only via confidence gate; dev writes to `vault/_sandbox/`
- HARD STOP before migrations, vault writes, deletes, `git push`, secrets
- Batched triage; cheap model for Sorter/Curator; opt-in Scout/Builder
