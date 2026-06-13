# Spore — STATUS

_Last updated: 2026-06-12. Update at the end of every session._

## Now
**ENTIRE BACKEND COMPLETE & LIVE.** All backend epics done: 1.1–1.3 + Epics 3,4,5,6,7,8,9 + real AI + n8n cron.
Autonomous loop runs hands-free: capture → n8n cron (2 min) → real Claude Haiku Sorter + LOCAL Ollama
embeddings → confidence gate → review queue → Builder skills (Sonnet) → git vault; idea pipeline state machine;
resurfacing/digests (Curator); reminders; cost dashboard + ops metrics; corrections feedback loop.
**122 tests green**; every layer verified live. Cost ~$0.0007/capture; $0 embeddings (local Ollama).
REMAINING needs YOU: **Epic 2 iOS** (SwiftUI, requires Xcode), and secret-gated delivery —
**1.4** Cloudflare Tunnel (TUNNEL_TOKEN), **1.5** Telegram (TELEGRAM_BOT_TOKEN), **APNs push** (.p8) wiring the notifier seam.

## Known ops nits
- api container runs as root → vault files on host owned by root (host `git` needs `safe.directory`). Add a non-root user to backend/Dockerfile later.

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
- [x] **Epic 5** — git-versioned vault writer (frontmatter/backlinks/MOC/atomic commits, FR16-19); 51 tests; verified live
- [x] **Real AI wired** — Claude Haiku Sorter (key in remote .env) + LOCAL Ollama embeddings (mxbai-embed-large 1024d); verified live end-to-end
- [x] **Epic 6** — declarative skills registry + Builder runtime (Sonnet build-out); /skills/{name}/run; starter skills; verified live
- [x] **Epic 7** — idea pipeline state machine + /pipeline API + promotion/stale rules; verified live (409 on invalid transition)
- [x] **n8n triage cron** — autonomous batched triage every 2 min (FR36); verified live auto-triage
- [x] **Epic 8** — reminders/resurfacing/Curator digests (FR30-33); notifier seam (delivery stubbed); verified live
- [x] **Epic 9** — cost dashboard + ops metrics + corrections feedback (FR35/37); 122 tests; verified live
- [x] **ALL BACKEND EPICS COMPLETE** (1,3,4,5,6,7,8,9). 122 tests green.

## Infra: Ollama
- `ollama` service in compose (internal-only). Model `mxbai-embed-large` pulled into `spore_ollama` volume.
  If recreated, re-pull: `docker compose exec ollama ollama pull mxbai-embed-large`.

## Next (all need YOU — Xcode or secrets)
1. **Epic 2 iOS** — SwiftUI capture app (shell, offline queue, review swipe, pipeline, widgets). I can write Swift; needs Xcode to compile/run.
2. **1.4** Cloudflare Tunnel — needs TUNNEL_TOKEN (external reach + POST /devices APNs registration)
3. **1.5** Telegram capture — needs TELEGRAM_BOT_TOKEN (zero-build capture channel; n8n webhook → /capture)
4. **APNs push** — wire the notify.py seam to real APNs (needs .p8 key) so reminders/digests deliver

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
