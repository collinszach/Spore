# Spore — Architecture (docs/ARCHITECTURE.md)

> **BMAD V6 · Solutioning phase.** Authored by spore-architect (Winston). Consumes docs/PRD.md + docs/SPEC.md.
> Hands off to scrum-master for sharding. Canonical schema lives in `backend/migrations/001_init.sql`.

---

## 1. System overview

```
┌─────────────────────────── iOS (SwiftUI) ── PRIMARY SURFACE ───────────────────────────┐
│  Capture (quick/Share/Siri/Widget/Voice)   Review (swipe)   Pipeline (Kanban)           │
│  Notes (read)   Today (digest)             SwiftData offline queue → sync                │
└───────────────────────────────────────────────┬────────────────────────────────────────┘
                                 HTTPS via Cloudflare Tunnel (no inbound ports)
┌───────────────────────────────────────────────┴──────────── NUC ────────────────────────┐
│  FastAPI (:8020)  ── REST: /capture /review /pipeline /skills /reminders                  │
│        │                                                                                  │
│        ├── Redis queue ── workers ──► RUNTIME AGENTS (Claude API)                          │
│        │                              Director → Sorter · Scout · Builder · Curator        │
│        │                                                                                   │
│        ├── Postgres + pgvector + Timescale   (machine state: captures, notes, embeddings) │
│        │                                                                                   │
│        └── Vault writer ──► Obsidian vault (git repo)  ◄── synced to iOS (Obsidian Sync)   │
│                                                                                            │
│  n8n (:5678) ── TRANSPORT ONLY: webhook ingest, cron triggers, push fan-out (APNs/TG/ntfy)│
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

**Four-layer contract:** iOS = surfaces · FastAPI+Claude = cognition · Obsidian = human prose · Postgres = authoritative machine state. n8n never reasons.

---

## 2. Component responsibilities

| Component | Owns | Must not |
|---|---|---|
| iOS app | capture, offline queue, review UX, pipeline board, notifications | call Claude directly; hold API keys |
| FastAPI | API contracts, auth, orchestration, vault writes, cost ledger | embed business logic in routers |
| Runtime agents | classification, enrichment, build-out, resurfacing | do scheduling or raw I/O |
| Postgres | state, embeddings, schedules | store canonical prose |
| Obsidian vault | human-readable notes, backlinks | be authoritative for routing/state |
| n8n | triggers, transport, push fan-out | classify, decide, or branch on content |
| Redis | job queue, rate-limited fan-in | durable storage |

---

## 3. Data model

Full DDL: `backend/migrations/001_init.sql`. Tables: `raw_capture` (Timescale hypertable), `note` (pgvector embedding, idea_state), `note_link`, `idea_event` (state-machine audit), `review_item`, `correction`, `reminder`, `skill_run` (cost ledger), `device` (APNs). Embedding dim **1024** (ADR-002). ANN via ivfflat cosine, retune to HNSW once data lands.

---

## 4. Runtime agent topology

```
Director (orchestrator, cheap model)
  ├─ Sorter   — triage: type/tags/domain/urgency/confidence + kNN related_ids   [cheap model]
  ├─ Scout    — enrich: web research + MOC placement (opt-in by type)           [strong model]
  ├─ Builder  — run a skills/*.skill.yaml against a note → vault output         [strong model]
  └─ Curator  — resurfacing: digests, spaced repetition, stale-idea nudges      [cheap model]
```

**Triage sequence (per batch):**
```
capture(pending) → embed → pgvector kNN → Sorter(JSON) → validate
  → confidence gate (§5) → {vault write | review_item} → mark triaged
  → if type=task: create reminder
```

Model split is the cost lever: Sorter/Curator on the cheap model (high volume), Scout/Builder on the strong model (low volume, opt-in). Every call writes a `skill_run` row.

---

## 5. Confidence gate (the core logic)

```python
def route(capture, triage):
    if triage.type == "task":
        create_reminder(capture, triage)            # always, regardless of confidence

    c = triage.routing_confidence
    if c >= DIRECT_WRITE_THRESHOLD:                  # default 0.80 (ADR-003)
        write_to_vault(triage, needs_review=False)
    elif c >= REVIEW_FLOOR:                          # 0.50
        write_to_vault(triage, needs_review=True)    # tagged #needs-review
        enqueue_review(capture, triage, reason="low_confidence")
    else:
        enqueue_review(capture, triage, reason="low_confidence")  # vault untouched

    if triage.duplicate_of:
        enqueue_review(capture, triage, reason="duplicate")
```

Invariant: **below the floor, the vault is never touched.** This is what keeps it clean.

---

## 6. API contracts (FastAPI :8020)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/health` | liveness | none |
| POST | `/capture` | create capture (all surfaces) | device token |
| GET | `/review?status=open` | list review queue | device token |
| POST | `/review/{id}/{action}` | approve\|redirect\|merge\|discard | device token |
| GET | `/pipeline` | ideas by state | device token |
| POST | `/pipeline/{note_id}/move` | transition idea state | device token |
| POST | `/skills/{name}/run` | run a runtime skill on a note | device token |
| GET | `/notes?q=` | search synced notes | device token |
| POST | `/reminders` | create reminder | device token |
| POST | `/devices` | register APNs token | device token |

Envelope: `{ok, data, error}`. All writes idempotent by client-supplied `capture_uuid` so offline-queue retries don't dupe.

---

## 7. n8n flows (transport only)

| Flow | Trigger | Action |
|---|---|---|
| capture-ingest | webhook (Telegram/email) | normalize → `POST /capture` |
| triage-cron | cron (1–2 min) | `POST /internal/triage-batch` |
| reminder-fire | cron (1 min) | due reminders → APNs/Telegram/ntfy |
| daily-digest | cron (07:00) | `GET /internal/digest/daily` → push |
| weekly-review | cron (Sun 17:00) | `GET /internal/digest/weekly` → push |
| stale-sweep | cron (daily) | flag stale seedlings → review/digest |

No flow inspects content to branch logic — it only moves bytes and fires timers.

---

## 8. Security & privacy
- Claude/embedding/APNs keys are **server-side only**; iOS never holds them (NFR5).
- Backend reachable only via Cloudflare Tunnel; zero inbound ports on the NUC (NFR4).
- Device-token auth on every endpoint; rotate on demand.
- Vault writes are git commits — every agent action is diffable and revertable (NFR2).
- `.claudeignore` keeps the vault and secrets out of any Claude Code context.

## 9. Cost model
Target ≤ $15/mo. Batched triage + cheap Sorter/Curator + opt-in Scout/Builder. `skill_run` ledger powers the in-app dashboard; weekly digest reports spend. Whisper local on the N95 if API transcription volume grows (ADR-001).

## 10. Observability
Structured logs with request id across capture→triage→route. Metrics: captures/day, triage latency, gate distribution (direct/review/floor), review-queue depth, $/day. Failures retry with backoff; captures never lost (NFR6/NFR8).

---

## 11. Architecture Decision Records

- **ADR-001 — Transcription:** *Recommend Whisper API for v1* (simplicity, pennies/min), switch to local `whisper.cpp` on the N95 only if monthly minutes make API cost material. Revisit at Epic 2.6.
- **ADR-002 — Embeddings:** *Recommend voyage-3-lite (1024-dim)* — strong retrieval, cheap, pairs well with Claude. Schema fixed at 1024; changing later means a reindex. Alternative: OpenAI text-embedding-3-small (1536).
- **ADR-003 — Direct-write threshold:** *Default 0.80.* Raise to 0.90 for a near-immaculate vault at the cost of a larger review queue. Tunable in config; logged in the gate distribution metric so you can calibrate from real data.
- **ADR-004 — Vault sync:** *Recommend Obsidian Sync* (reliable, low-effort) over Syncthing for v1; the app only needs read sync, so this is non-blocking for the backend.
- **ADR-005 — Telegram fallback:** *Keep as permanent secondary.* It's the zero-build capture path that lets you validate triage before the iOS app exists, and a useful redundancy after.
```
