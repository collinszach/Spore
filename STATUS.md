# Spore — STATUS

_Last updated: 2026-06-12. Update at the end of every session._

## Now
Capture → triage → review spine LIVE. **Stories 1.1–1.3 + Epic 3 + Epic 4 DONE.**
/capture → /internal/triage-batch (confidence gate) → /review (approve|redirect|merge|discard + corrections).
All verified live; 36 tests green on remote Postgres. Triage runs on deterministic FAKE clients until
ANTHROPIC_API_KEY + VOYAGE_API_KEY are set on the remote .env.
Next options: **wire live keys** (real Claude/Voyage), **Epic 5 vault writer** (fill the NoOpVaultWriter
seam — Obsidian markdown + git, FR16-19), **Epic 2 iOS** (Xcode), or **1.4/1.5** (need TUNNEL_TOKEN / TELEGRAM_BOT_TOKEN).

## Remote ops note
- Host `100.91.198.28` rebooted once mid-build; containers don't auto-start. Recover with:
  `ssh zach@100.91.198.28 'cd ~/spore && docker compose up -d db redis api n8n'`.

## Test harness (remote)
- DB tests run in a transient python:3.12 container on the `spore_default` network against a
  `spore_test` DB (schema pre-applied). `docker run --network spore_default -e DATABASE_URL=...@db:5432/spore_test`.
- Full suite: 10 passed (health + repos + /capture contract). pytest log_level=INFO.

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
- [x] **Story 1.2** — async data layer + repositories (CRUD + pgvector kNN); 4 tests
- [x] **Story 1.3** — authed idempotent POST /capture; 10 tests; verified live
- [x] **Epic 3** — Sorter + embeddings + dedup + confidence gate; /internal/triage-batch; 23 tests; verified live
- [x] **Epic 4** — review-queue API (approve/redirect/merge/discard) + corrections (FR13/14); 36 tests; verified live

## Next 3 stories
1. **Wire live keys** — set ANTHROPIC_API_KEY + VOYAGE_API_KEY on remote .env; real Sorter/embeddings
2. **Epic 5** vault writer — fill NoOpVaultWriter seam: Obsidian markdown + YAML frontmatter + git commits (FR16-19)
3. **Epic 2** iOS app shell + offline capture queue (Xcode) — or **1.4/1.5** once secrets provided

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
