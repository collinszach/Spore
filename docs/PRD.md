# Spore — Product Requirements Document (PRD)

> **Framework:** BMAD-METHOD™ V6 · Planning Phase artifact
> **Authored by:** PM (John) · **Consumes:** Project Brief (Analyst) · **Hands off to:** Architect → Scrum Master (sharding)
> **Phase map:** Analysis ✅ → **Planning (this doc)** → Solutioning (Architecture) → Implementation (sharded stories)
> **Primary surface:** iOS (SwiftUI) · **Backend:** Beelink NUC (FastAPI + Postgres/pgvector) · **Cognition:** Claude API subagents

---

## 1. Goals & Background Context

### Goals
- Capture any fleeting thought from iOS in **under 3 seconds**, from anywhere (in-app, Share Sheet, Siri, widget, lock screen).
- Automatically triage, enrich, and route thoughts into a **clean, structured Obsidian vault** — without polluting it.
- Mature raw ideas through a **pipeline** (Seedling → Project) and build them out via **declarative skills**.
- **Resurface** ideas and fire reminders so nothing dies in the inbox.
- Keep monthly cost in the **~$10–15** envelope; run entirely on existing NUC + Claude API.

### Background Context
Existing capture→PKM tools fail because they optimize ingestion and ignore curation — auto-writing raw thoughts turns a vault into a landfill. Spore inverts this: a confidence gate and native review flow keep the vault sacred, while subagents handle classification, linking, and build-out. iOS is primary because capture friction is the dominant failure mode, and native affordances (Share Sheet, Shortcuts, widgets, Live Activities, local notifications) are the lowest-friction surfaces available.

### Change Log
| Date | Version | Description | Author |
|---|---|---|---|
| 2026-06-11 | 0.1.0 | Initial PRD, iOS-primary | PM (John) |

---

## 2. Requirements

### Functional (FR)

**Capture**
- **FR1** — In-app quick capture: single textarea, opens to keyboard focus, saves on submit, works offline (local queue, syncs on reconnect).
- **FR2** — Share Sheet extension: send selected text / URL / image from any iOS app into Spore's inbox.
- **FR3** — Siri / App Intents: "Note to Spore" → dictation → inbox item.
- **FR4** — Home/lock-screen widget + Control Center control + back-tap shortcut for one-tap capture.
- **FR5** — Voice capture: record audio in-app or via Share Sheet → transcribe (Whisper) → text inbox item; original audio retained.
- **FR6** — Email-to-inbox and Telegram bot as secondary capture surfaces routing to the same inbox.
- **FR7** — Every capture normalizes to a `raw_capture` record with source, body, optional media, and timestamp.

**Triage & Intelligence**
- **FR8** — Sorter subagent classifies each capture: type, tags, domain, urgency, actionability, routing confidence (0–1).
- **FR9** — Atomic decomposition: a multi-idea capture is split into N atomic notes.
- **FR10** — Embedding + pgvector kNN search surfaces related existing notes as backlink candidates.
- **FR11** — Near-duplicate detection flags captures that overlap existing notes above a similarity threshold.

**Routing & Review**
- **FR12** — Confidence gate: ≥0.80 writes to vault directly; 0.50–0.80 writes with `#needs-review`; <0.50 goes to review queue only.
- **FR13** — Native review queue: swipeable card stack to Approve / Redirect / Merge / Discard each item.
- **FR14** — Redirecting or correcting a routed item logs a `correction` record (training signal).
- **FR15** — Task-type captures always create a reminder regardless of confidence.

**Obsidian Vault**
- **FR16** — Routed notes are written as Markdown with YAML frontmatter (created, source, type, status, tags, links).
- **FR17** — Backlinks are inserted bidirectionally between related notes.
- **FR18** — Vault is a git repo; every agent write is an atomic, reverting commit.
- **FR19** — Notes are placed into a PARA-style folder structure and linked from the relevant MOC.
- **FR20** — Vault changes sync to iOS (read access) so notes are viewable in-app.

**Skills & Build-out**
- **FR21** — Declarative skills registry: each skill is a YAML/MD file (trigger, input types, prompt, output template, post-actions).
- **FR22** — Builder subagent executes a skill against a note and writes structured output to the vault.
- **FR23** — Starter skills: `expand_to_spec`, `literature_note`, `decision_doc`, `atomic_split`, `merge_duplicates`, `daily_review`, `weekly_review`.
- **FR24** — `expand_to_spec` scaffolds a `SPEC.md` + project folder and can hand off to the director-agent workflow.
- **FR25** — Skills can be triggered manually (in-app), on state change, or on schedule.

**Idea Pipeline**
- **FR26** — Idea state machine: Seedling → Sapling → Sprout → Project → Shipped / Archived.
- **FR27** — In-app pipeline board (Kanban) to view and move ideas across states.
- **FR28** — Rule-based promotion suggestions (e.g., note referenced 3+ times → suggest promote).
- **FR29** — Stale-idea detection: Seedlings untouched for N days are flagged for promote/merge/archive.

**Resurfacing & Reminders**
- **FR30** — Local notifications for reminders at due time; recurring reminders supported.
- **FR31** — Spaced resurfacing schedule (e.g., 1d/3d/1w/1m) re-presents notes for review.
- **FR32** — Daily digest (morning): review queue count, today's reminders, one resurfaced idea.
- **FR33** — Weekly review digest: orphan notes, dangling links, promotion-ready ideas.
- **FR34** — Live Activity / Dynamic Island for in-flight build-out runs and imminent reminders.

**System & Feedback**
- **FR35** — Per-skill-run cost logging; in-app cost dashboard with weekly spend.
- **FR36** — Triage batched on a short cron to reduce per-message API cost.
- **FR37** — Corrections feed periodic prompt refinement for the Sorter.

### Non-Functional (NFR)
- **NFR1** — Capture-to-saved latency < 500ms on-device (excludes async triage).
- **NFR2** — All vault writes are atomic and reversible via git.
- **NFR3** — Monthly run cost ≤ $15 at expected volume; web research is opt-in by type.
- **NFR4** — Backend reachable only via Cloudflare Tunnel; no inbound ports on the NUC.
- **NFR5** — Secrets never committed (`.claudeignore` / `.env`); API keys server-side only, never in the iOS binary.
- **NFR6** — Offline-first capture: no thought is ever lost due to connectivity.
- **NFR7** — iOS app runs on iOS 17+; uses App Intents, WidgetKit, ActivityKit, BackgroundTasks.
- **NFR8** — System degrades gracefully if Claude API is unavailable (captures queue, triage retries).

---

## 3. UI Design Goals

### UX Vision
A capture tool that feels frictionless and a review tool that feels like clearing a tiny, satisfying queue. Two modes dominate: **dump** (instant, zero-chrome) and **tend** (swipe through review/resurfacing cards). Everything else is secondary.

### Core Screens / Surfaces
- **Capture** — default launch state; textarea + mic, instant save.
- **Inbox / Review** — swipeable card stack; Approve / Redirect / Merge / Discard.
- **Pipeline** — Kanban board of ideas by state.
- **Notes** — read-only browse/search of the synced vault.
- **Resurface / Today** — daily digest, reminders, one resurfaced idea.
- **Settings** — sync, thresholds, skills, cost dashboard.

### Interaction Targets
- Share Sheet, Siri/App Intents, Widget, Control Center control, back-tap.
- Swipe-driven review; haptics on approve/route.
- Live Activity for build-out runs and imminent reminders.

### Branding / Platform
- Native SwiftUI, system fonts, light/dark. iPhone primary; iPad later.

---

## 4. Technical Assumptions

- **Client:** Swift / SwiftUI, App Intents, WidgetKit, ActivityKit, BackgroundTasks, on-device queue (SwiftData/SQLite).
- **Backend:** Python 3.12 / FastAPI on the NUC; Docker Compose.
- **Data:** PostgreSQL + pgvector + TimescaleDB; Redis (job queue).
- **Cognition:** Claude API subagents — Director orchestrates Sorter / Scout / Builder / Curator.
- **Orchestration:** n8n for transport/scheduling only (no reasoning).
- **Vault:** Obsidian vault on NUC, git-versioned, synced via Obsidian Sync or Syncthing.
- **Transcription:** Whisper (API or local `whisper.cpp`).
- **Notify:** APNs (local + push), Telegram, ntfy.
- **Ingress:** Cloudflare Tunnel.
- **Repo:** monorepo — `ios/`, `backend/`, `skills/`, `n8n/`, `vault/` (submodule).
- **Testing:** XCTest (client), pytest (backend), contract tests on the capture/triage API.

---

## 5. Epic List

1. **Backend Spine & Foundations** — API, data layer, auth, tunnel, Telegram fallback capture.
2. **iOS App Shell & Capture Surfaces** — SwiftUI app, quick capture, Share Sheet, Siri, widget, voice, offline queue.
3. **Triage & Intelligence** — Sorter subagent, embeddings, dedup, confidence scoring.
4. **Routing & Native Review Queue** — confidence gate, swipe review, corrections.
5. **Obsidian Vault Integration** — frontmatter, backlinks, git sync, MOCs, in-app read.
6. **Skills Engine & Build-out** — declarative skills, Builder subagent, starter skill set, director-agent handoff.
7. **Idea Pipeline & State Machine** — states, Kanban board, promotion rules, stale-idea nudges.
8. **Resurfacing & Reminders** — local notifications, spaced repetition, digests, Live Activities.
9. **Feedback Loop, Cost & Ops** — corrections→prompt tuning, cost dashboard, observability.

---

## 6. Epic Details

### Epic 1 — Backend Spine & Foundations
*Goal: a deployable backend that can accept and store a capture end-to-end.*
- **1.1** Docker Compose: Postgres+pgvector+TimescaleDB, Redis, FastAPI, n8n. **AC:** `docker compose up` boots all services; healthcheck passes.
- **1.2** Data model migrations (`raw_capture`, `note`, `note_link`, `review_item`, `reminder`, `skill_run`, `correction`). **AC:** migrations apply cleanly; pgvector extension enabled.
- **1.3** `POST /capture` endpoint with auth token. **AC:** valid request creates `raw_capture`; invalid token → 401.
- **1.4** Cloudflare Tunnel + device auth. **AC:** endpoint reachable externally with no open inbound ports.
- **1.5** Telegram bot fallback capture → `/capture`. **AC:** text and voice messages create captures.

### Epic 2 — iOS App Shell & Capture Surfaces
*Goal: capture a thought from every native surface in <3s, offline-safe.*
- **2.1** SwiftUI app shell + tab structure (Capture / Review / Pipeline / Notes / Today). **AC:** app launches to Capture with keyboard focused.
- **2.2** Quick capture + on-device queue (SwiftData). **AC:** capture saves locally in <500ms; syncs to backend when online; survives airplane mode.
- **2.3** Share Sheet extension (text/URL/image). **AC:** sharing from Safari/Mail creates a capture with source metadata.
- **2.4** App Intents + Siri ("Note to Spore"). **AC:** Siri dictation creates a capture hands-free.
- **2.5** Widget + Control Center control + back-tap. **AC:** each opens capture or one-shot dictation.
- **2.6** Voice capture + Whisper transcription. **AC:** recording produces a transcribed capture; audio retained and linked.

### Epic 3 — Triage & Intelligence
*Goal: every capture is classified, atomized, and linked.*
- **3.1** Sorter subagent + structured JSON output. **AC:** capture yields type/tags/domain/urgency/confidence.
- **3.2** Batched triage cron. **AC:** captures triaged within the batch window; cost per item logged.
- **3.3** Embeddings + pgvector kNN. **AC:** related notes returned for a capture above similarity threshold.
- **3.4** Atomic decomposition. **AC:** multi-idea capture produces multiple atomic notes.
- **3.5** Near-duplicate detection. **AC:** overlapping capture flagged with the matched note(s).

### Epic 4 — Routing & Native Review Queue
*Goal: clean vault via confidence gating and a fast review UX.*
- **4.1** Confidence-gate router. **AC:** items route per thresholds; tasks always create reminders.
- **4.2** Review queue API (list/approve/redirect/merge/discard). **AC:** actions update state and trigger vault writes on approve.
- **4.3** Swipeable review UI. **AC:** swipe gestures map to actions with haptics; empties queue.
- **4.4** Corrections logging. **AC:** redirect/edit writes a `correction` record.

### Epic 5 — Obsidian Vault Integration
*Goal: notes land as clean, linked, reversible Markdown.*
- **5.1** Frontmatter + Markdown writer. **AC:** notes written with complete YAML frontmatter to correct PARA folder.
- **5.2** Bidirectional backlinks. **AC:** approved note links to/from related notes.
- **5.3** Git-versioned writes. **AC:** each write is one commit; revertable.
- **5.4** MOC linking. **AC:** note added to the relevant MOC index.
- **5.5** In-app read sync. **AC:** synced notes are browsable/searchable in the Notes tab.

### Epic 6 — Skills Engine & Build-out
*Goal: turn ideas into structured artifacts via declarative skills.*
- **6.1** Declarative skill loader (YAML/MD). **AC:** dropping a skill file registers it without code changes.
- **6.2** Builder subagent runtime. **AC:** running a skill on a note writes templated output to the vault.
- **6.3** Starter skills (`literature_note`, `decision_doc`, `atomic_split`, `merge_duplicates`). **AC:** each produces its defined output.
- **6.4** `expand_to_spec` + director-agent handoff. **AC:** promoting an idea scaffolds `SPEC.md` + folder and can launch the director prompt.
- **6.5** Trigger modes (manual/on-state/scheduled). **AC:** all three invoke skills correctly.

### Epic 7 — Idea Pipeline & State Machine
*Goal: ideas mature visibly instead of rotting in the inbox.*
- **7.1** State machine + persistence. **AC:** valid transitions enforced; invalid blocked.
- **7.2** Kanban board UI. **AC:** drag moves ideas across states; state persists.
- **7.3** Promotion-suggestion rules. **AC:** reference-count rule surfaces a promote suggestion.
- **7.4** Stale-idea detection. **AC:** stale Seedlings appear in the weekly digest with actions.

### Epic 8 — Resurfacing & Reminders
*Goal: nothing is forgotten.*
- **8.1** Local + push notifications (APNs). **AC:** reminder fires at due time; recurrence honored.
- **8.2** Spaced resurfacing engine. **AC:** notes re-presented on the decay schedule.
- **8.3** Daily + weekly digests. **AC:** digests delivered with correct contents.
- **8.4** Live Activity / Dynamic Island. **AC:** build-out runs and imminent reminders show live status.

### Epic 9 — Feedback Loop, Cost & Ops
*Goal: the system improves and stays cheap.*
- **9.1** Cost dashboard. **AC:** weekly spend and per-skill cost visible in-app.
- **9.2** Corrections → prompt tuning loop. **AC:** correction set feeds a periodic Sorter prompt update.
- **9.3** Observability. **AC:** structured logs + basic metrics for pipeline stages and failures.
- **9.4** Graceful degradation. **AC:** API outage queues captures and retries triage without loss.

---

## 7. Open Decisions (resolve before Architecture phase)
1. Vault sync: Obsidian Sync vs Syncthing.
2. Whisper: API vs local `whisper.cpp` on the N95.
3. Direct-write threshold: 0.80 default vs 0.90 (cleaner vault, bigger queue).
4. ~~Name~~ — RESOLVED: Spore.
5. Telegram fallback: keep as permanent secondary, or iOS-only after launch?

## 8. Next Steps
- **Architect (Winston):** produce the Full-Stack Architecture doc from this PRD (iOS module, backend, data, agent topology, n8n flows).
- **Scrum Master:** shard epics into context-rich story files with embedded tests.
- **PO:** validate scope vs MVP; defer iPad and non-essential skills if needed.
