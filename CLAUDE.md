# Spore — Project Memory

## What this is
iOS-primary thought-capture → Obsidian automation platform. SwiftUI app is the hero
surface; FastAPI + Postgres/pgvector on a Beelink NUC is the cognition+storage spine.
Runtime cognition = Claude API subagents (Director → Sorter/Scout/Builder/Curator).
n8n is transport/scheduling ONLY — it never reasons.

Source of truth: docs/PRD.md (BMAD V6) and docs/SPEC.md. Read both before non-trivial work.

## Operating rules (hard)
1. PREDICT BEFORE ACT: before any edit, state the files you'll touch and the expected diff.
2. SURGICAL EDITS: smallest change that satisfies the story. No drive-by refactors.
3. TRACE DEPENDENCIES: before editing a shared module, grep its callers and list blast radius.
4. CONVENTIONAL COMMITS: feat:, fix:, chore:, docs:, test: — one logical change per commit.
5. HARD STOP + ASK before: schema migrations, vault writes, deleting files, `git push`,
   anything touching secrets or APNs/production creds.
6. THE VAULT IS SACRED: nothing writes to vault/ except via the confidence gate (FR12).
   In dev, write to vault/_sandbox/ unless explicitly told otherwise.
7. COST DISCIPLINE: runtime triage is batched, web research opt-in. Log skill_run.cost_usd.

## Agent layers (do not conflate)
- BUILD-TIME subagents (.claude/agents/) write Spore's code. The **Director/PM runs on
  Opus and is the only Opus**; every build-time subagent runs Sonnet or Haiku to save tokens.
- RUNTIME agents (backend/agents/) run Spore's pipeline on real captures (Claude API).

## Delegation
- Architecture/design questions → spore-architect (read-mostly).
- SwiftUI / App Intents / WidgetKit / ActivityKit → ios-engineer.
- FastAPI / Postgres / pgvector / migrations → backend-engineer.
- Runtime Claude API agents + skill loader → agent-engineer.
- Tests + review before any merge → qa-reviewer.
- Turning an epic into story files → scrum-master.

## Stack
Swift/SwiftUI (iOS 17+, App Intents, WidgetKit, ActivityKit, BackgroundTasks, SwiftData) ·
Python 3.12 / FastAPI · Postgres + pgvector + TimescaleDB · Redis · Claude API ·
n8n · Whisper · APNs/Telegram/ntfy · Cloudflare Tunnel · Docker Compose.
API on :8020 (avoid KoastCast 8010/8011).

## Definition of done (per story)
Code + tests pass (XCTest / pytest) + acceptance criteria met + STATUS.md updated +
conventional commit. No story is "done" without its AC verified.

## Session protocol
Start: read STATUS.md + relevant docs. End: update STATUS.md (done / in-progress / blockers / next).
