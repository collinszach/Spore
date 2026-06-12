# Spore — SPEC.md

> Name: **Spore** — raw thoughts propagate, germinate, and grow into structured knowledge. Pairs with Hive.
> Capture random thoughts → triage → enrich → route into a structured Obsidian vault → build them out → resurface them on schedule.

**Version:** 0.1.0 (spec)
**Owner:** Zach
**Host:** Beelink NUC (Intel N95, 16GB) — synthesis via Claude API (no local LLM)

---

## 1. Problem & Philosophy

Thought-capture-to-PKM systems fail for one reason: **they treat ingestion as the hard part.** It isn't. The hard part is that auto-writing raw thoughts into a vault turns it into a landfill of orphaned, duplicate, mislabeled notes.

Spore's design principles:

1. **Capture friction → zero.** A thought must land in under 3 seconds from any surface.
2. **The vault is sacred.** Nothing enters it without passing a confidence gate. Ambiguous items go to a review queue, not the vault.
3. **n8n is plumbing, not a brain.** All reasoning lives in Claude subagents. n8n only moves bytes and fires timers.
4. **Two-layer truth.** Obsidian = human-readable prose. Postgres/pgvector = machine state. They mirror each other; the machine layer is authoritative for routing/state.
5. **Skills are declarative.** Build-out behaviors are config files, not code. Add a skill = add a file.
6. **Resurfacing is a first-class feature**, not an afterthought. An idea you never see again is a lost idea.

---

## 2. The Pipeline

```
        ┌──────────┐   ┌─────────┐   ┌──────────┐   ┌────────┐   ┌───────────┐   ┌────────────┐
 INPUT →│ CAPTURE  │ → │ TRIAGE  │ → │ ENRICH   │ → │ ROUTE  │ → │ BUILD-OUT │ → │ RESURFACE  │
        └──────────┘   └─────────┘   └──────────┘   └────────┘   └───────────┘   └────────────┘
         multi-surface  classify+      link+web      vault vs      skills run      reminders+
         → raw inbox    atomize        research      review queue  on demand       spaced repeat
```

### 2.1 Capture
Surfaces, in priority order:

| Surface | Mechanism | Notes |
|---|---|---|
| Telegram bot | webhook → n8n → inbox | Primary. Text + voice notes. |
| Voice | Telegram voice → Whisper (API or local `whisper.cpp`) | Transcribe → text inbox item |
| PWA quick-capture | FastAPI `POST /capture` | Home-screen icon, one textarea, offline queue |
| Email-to-inbox | dedicated address → n8n IMAP trigger | Forward articles/thoughts |
| Obsidian Quick Add | writes to `00_Inbox/` | App watches folder |

All surfaces normalize to a single `raw_capture` row + a stub file in `00_Inbox/`.

### 2.2 Triage (Subagent: **Sorter**)
Single Claude call per capture (batched on a 1–2 min cron to control cost). Outputs structured JSON:

```json
{
  "type": "fleeting | project_idea | task | reference | question | journal",
  "atomic_notes": ["...split rambling thought into atomic units..."],
  "tags": ["#topic", "..."],
  "domain": "career | koastcast | argus | personal | ...",
  "urgency": "now | soon | someday | none",
  "actionable": true,
  "related_note_ids": ["...from pgvector similarity search..."],
  "routing_confidence": 0.0-1.0,
  "suggested_path": "20_Projects/KoastCast/...",
  "suggested_skill": "expand_to_spec | null"
}
```

Key behaviors:
- **Atomic decomposition:** one messy capture → N atomic notes when warranted.
- **Dedup/link:** embed the capture, kNN search the vault via pgvector, attach backlink candidates.
- **Confidence score** drives routing (see 2.4).

### 2.3 Enrich (Subagent: **Scout**, conditional)
Runs only when `type ∈ {project_idea, reference, question}` and confidence warrants:
- Web search (Claude w/ web_search tool) to add 2–4 sourced bullets + links.
- Suggest the right **MOC** (Map of Content) placement.
- Generate frontmatter (created, source, status, tags, links).

### 2.4 Route — the confidence gate
```
routing_confidence ≥ 0.80  → write directly to vault (with frontmatter + backlinks)
0.50 ≤ confidence < 0.80   → write to vault but tag #needs-review + add to review queue
confidence < 0.50          → review queue ONLY (never touches main vault)
type == task               → also create reminder (§2.6), regardless of confidence
```
**Review queue** = a Telegram digest + a `_Review/` Kanban note. You approve/redirect with a tap. Approvals become training signal (log corrections to improve prompts over time).

### 2.5 Build-out (Subagent: **Builder** + Skills)
The "pipeline ideas, build them out" layer. Skills are declarative (§4). An idea matures through a state machine:

```
🌱 Seedling → 🌿 Sapling → 🌲 Sprout → 🏗️ Project → ✅ Shipped / 🪦 Archived
```

- Promotion is manual (you tap) or rule-based (e.g., idea referenced 3+ times → suggest promotion).
- Promoting to **Project** can auto-run the `expand_to_spec` skill → scaffolds a `SPEC.md` + folder, ready for your **director-agent** workflow.

### 2.6 Resurface (Subagent: **Curator**)
The anti-landfill engine. Cron-driven, delivered via Telegram/ntfy:
- **Reminders:** task items with `urgency` → push at due time.
- **Spaced resurfacing:** notes re-presented on a decay schedule (1d, 3d, 1w, 1m) so ideas don't die in `00_Inbox/`.
- **Stale-idea nudge:** Seedlings untouched for N days → "promote, merge, or archive?"
- **Daily digest:** morning — review queue + today's reminders + 1 resurfaced idea.
- **Weekly review:** orphan notes, dangling links, ideas ripe for promotion.

---

## 3. Architecture

```
 CAPTURE SURFACES            ORCHESTRATION (dumb)        COGNITION (Claude subagents)
 Telegram / PWA / Email ──►  n8n  ──webhook/cron──►  FastAPI ──►  Director
                                   │                              ├─ Sorter   (triage)
                             push/notify◄──────────────┐          ├─ Scout    (enrich)
                                   │                    │          ├─ Builder  (skills)
                             ntfy / Telegram            │          └─ Curator  (resurface)
                                                        │
 STATE                                                  │   HUMAN LAYER
 Postgres + pgvector ◄──────────────────────────────────┘   Obsidian vault (git repo)
 (inbox, embeddings,                                        00_Inbox/ 10_Notes/ 20_Projects/
  idea_state, reminders)                                    30_Reference/ 40_MOCs/ _Review/
 Redis (queue) · TimescaleDB (capture timeseries)
```

### Stack (mirrors your existing rigs)
- **API/brain:** Python 3.12, FastAPI
- **Orchestration:** n8n (self-hosted, Docker)
- **Cognition:** Claude API (Sorter/Scout/Builder/Curator = Director + subagents)
- **Data:** PostgreSQL + pgvector + TimescaleDB; Redis (job queue)
- **Vault sync:** Obsidian vault on NUC, git-versioned, synced via Obsidian Sync or Syncthing
- **Transcription:** Whisper (API, or `whisper.cpp` if you want $0)
- **Notify:** Telegram Bot API + ntfy
- **Ingress:** Cloudflare Tunnel
- **Deploy:** Docker Compose; secrets via `.env` + `.claudeignore`

### Division of labor (the rule that prevents mush)
| Layer | Does | Never does |
|---|---|---|
| n8n | triggers, transport, notify, fan-out | reasoning, classification |
| Claude subagents | all decisions, writing, linking | scheduling, raw I/O plumbing |
| Obsidian | human reading/editing | authoritative state |
| Postgres | state, embeddings, scheduling | prose storage |

---

## 4. Skills (declarative registry)

Each skill is a file in `skills/`. Shape mirrors Anthropic Skills + your SPEC/CLAUDE.md conventions, so adding capability = adding a file, no code.

```yaml
# skills/expand_to_spec.skill.yaml
name: expand_to_spec
trigger:
  on_promote_to: project          # or: manual, on_capture, on_schedule
  input_types: [project_idea]
prompt: |
  You are Builder. Turn this idea note into a SPEC.md scaffold using the
  user's standard structure (Problem, Architecture, Data Model, Backlog).
  Pull in linked notes and any Scout research already attached.
output:
  template: templates/spec_scaffold.md
  path: "20_Projects/{{slug}}/SPEC.md"
post_actions:
  - create_folder: "20_Projects/{{slug}}"
  - set_idea_state: project
  - notify: telegram
```

Starter skill set:
- **expand_to_spec** — idea → SPEC.md scaffold (hands to director-agent).
- **literature_note** — URL/reference → summarized, sourced note w/ backlinks.
- **decision_doc** — question → options / tradeoffs / recommendation.
- **atomic_split** — explicit re-decomposition of an overgrown note.
- **daily_review / weekly_review** — Curator digests.
- **merge_duplicates** — collapse near-identical notes flagged by pgvector.

---

## 5. Data Model (core tables)

```sql
raw_capture(id, source, body, media_url, transcribed, created_at)
note(id, vault_path, type, domain, tags[], idea_state, confidence,
     embedding vector(1024), created_at, updated_at)
note_link(src_id, dst_id, kind)             -- backlinks/relations
review_item(id, capture_id, reason, status, suggested_path, created_at)
reminder(id, note_id, fire_at, channel, recurrence, status)
skill_run(id, skill, note_id, status, output_path, cost_usd, created_at)
correction(id, review_item_id, original_json, corrected_json, created_at)  -- training signal
```

---

## 6. Vault Structure (PARA-ish)

```
00_Inbox/        raw stubs, pre-routing
10_Notes/        atomic permanent notes
20_Projects/     active builds (KoastCast, Argus, ... + new spawns)
30_Reference/    literature/source notes
40_MOCs/         Maps of Content (entry points)
_Review/         confidence-gated items awaiting your tap
_Templates/      frontmatter + skill output templates
```

---

## 7. Cost Control (you care about this)

- Triage batched on a 1–2 min cron, not per-message → fewer, fatter calls.
- Scout (web research) is **opt-in by type**, not default.
- Cheap model for Sorter/dedup classification; stronger model only for build-out skills.
- Whisper local (`whisper.cpp`) if transcription volume grows.
- Target envelope: **~$10–15/month** active (in line with Argus).
- Log `cost_usd` per `skill_run`; weekly digest reports spend.

---

## 8. Build Order (epics)

- **Epic 0 — Foundations:** Docker Compose, Postgres+pgvector, FastAPI skeleton, vault git repo, Telegram bot echo.
- **Epic 1 — Capture:** Telegram + PWA + voice→Whisper → `raw_capture`.
- **Epic 2 — Triage:** Sorter subagent, embeddings, dedup search, confidence scoring.
- **Epic 3 — Route + Review queue:** confidence gate, vault writes w/ frontmatter, Telegram approve/redirect.
- **Epic 4 — Skills engine:** declarative loader, `expand_to_spec` + `literature_note`.
- **Epic 5 — Resurface:** reminders, spaced repetition, daily/weekly digests.
- **Epic 6 — Idea state machine:** promotion rules, stale-idea nudges.
- **Epic 7 — Feedback loop:** corrections → prompt tuning; cost dashboard.

---

## 9. Open Decisions (confirm before build)

1. **Vault sync:** Obsidian Sync (paid, clean) vs Syncthing (free, fiddly)? Spec assumes either; pick one.
2. **Whisper:** API (simple, ~pennies) vs local `whisper.cpp` ($0, uses NUC CPU)? N95 can handle small/base models.
3. **Direct-write threshold:** 0.80 default — raise to 0.90 if you want the vault near-immaculate and don't mind a bigger review queue.
4. ~~Name~~ — RESOLVED: Spore.
```
