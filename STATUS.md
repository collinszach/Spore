# Spore — STATUS

_Last updated: 2026-06-12 (seed). Update at the end of every session._

## Now
Planning complete. Repo not yet scaffolded. Next action: **Story 1.1 — stand up the stack.**

## Done
- [x] SPEC.md (architecture)
- [x] PRD.md (BMAD V6: 37 FR, 8 NFR, 9 epics)
- [x] ARCHITECTURE.md (agent topology, schema, gate logic, ADRs)
- [x] Claude Code kit (6 subagents, 3 dev skills, 4 commands, MCP, tools matrix)
- [x] Stories sharded: Epic 1 + Epic 2
- [x] Infra seeds: docker-compose.yml, 001_init.sql

## In progress
- [ ] Repo scaffold (drop kit into `.claude/`, move docs into `docs/`, `git init`)

## Next 3 stories
1. **1.1** stand up stack (backend-engineer) — HARD STOP before migrations
2. **1.3** `/capture` endpoint (backend-engineer)
3. **2.2** quick capture + offline queue (ios-engineer)

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
