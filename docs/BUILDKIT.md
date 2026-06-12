# Spore — Claude Code Build Kit

> Everything to build Spore in Claude Code: repo layout, `CLAUDE.md`, MCP config, build-time **subagents**, dev + runtime **skills**, slash **commands**, a least-privilege **tools matrix**, and a **build sequence**.
> Verified against Claude Code's current conventions: subagents are `.claude/agents/*.md` (YAML frontmatter: `name`, `description`, optional `tools`, `model`, `skills`; body = system prompt); skills are `.claude/skills/<name>/SKILL.md`; project MCP servers live in `.mcp.json`.

---

## 0. Two agent layers (do not conflate)

| | Build-time (Claude Code) | Runtime (Claude API, inside the app) |
|---|---|---|
| **Who** | architect, ios-engineer, backend-engineer, agent-engineer, qa-reviewer, scrum-master | Director → Sorter, Scout, Builder, Curator |
| **Where** | `.claude/agents/*.md` | `backend/agents/*.py` |
| **Job** | write Spore's code | run Spore's pipeline on real captures |
| **Skills** | `.claude/skills/` (dev helpers) | `skills/` registry at repo root (FR21) |

This kit builds the left column and scaffolds the right.

---

## 1. Repo layout

```
spore/
├── CLAUDE.md                      # project memory (below)
├── STATUS.md                      # live session state, updated each session
├── .claudeignore                  # secrets, vault, build artifacts
├── .mcp.json                      # project MCP servers
├── .claude/
│   ├── agents/                    # BUILD-TIME subagents
│   │   ├── spore-architect.md
│   │   ├── ios-engineer.md
│   │   ├── backend-engineer.md
│   │   ├── agent-engineer.md
│   │   ├── qa-reviewer.md
│   │   └── scrum-master.md
│   ├── skills/                    # BUILD-TIME skills
│   │   ├── swiftui-screen/SKILL.md
│   │   ├── fastapi-endpoint/SKILL.md
│   │   └── shard-epic/SKILL.md
│   └── commands/                  # slash commands
│       ├── status.md
│       ├── triage-run.md
│       ├── new-runtime-skill.md
│       └── ship.md
├── docs/
│   ├── PRD.md                     # (from prior step)
│   ├── SPEC.md
│   └── ARCHITECTURE.md            # produced by spore-architect
├── ios/                           # SwiftUI app
├── backend/
│   ├── app/                       # FastAPI
│   ├── agents/                    # RUNTIME Claude API agents (sorter.py, scout.py, ...)
│   └── migrations/
├── skills/                        # RUNTIME skill registry (the product's skills)
│   ├── expand_to_spec.skill.yaml
│   ├── literature_note.skill.yaml
│   └── decision_doc.skill.yaml
├── n8n/                           # exported workflow JSON
└── vault/                         # Obsidian vault (git submodule)
```

---

## 2. CLAUDE.md (god-version)

```markdown
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

## Definition of done (per story)
Code + tests pass (XCTest / pytest) + acceptance criteria met + STATUS.md updated +
conventional commit. No story is "done" without its AC verified.

## Session protocol
Start: read STATUS.md + relevant docs. End: update STATUS.md (done / in-progress / blockers / next).
```

---

## 3. .claudeignore

```
.env
*.env
**/secrets/**
vault/**            # never load the whole vault into context
!vault/_sandbox/**  # except the dev sandbox
ios/build/**
**/__pycache__/**
*.ipa
*.p8                # APNs key
```

---

## 4. .mcp.json (project MCP servers)

```json
{
  "mcpServers": {
    "postgres": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres",
               "postgresql://spore:spore@localhost:5432/spore"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}" }
    }
  }
}
```

> Add a `filesystem` server scoped to `vault/` only if you want agents to read notes during
> dev — but keep it read-path; writes go through the app's confidence gate, not MCP.

---

## 5. Build-time subagents

### `.claude/agents/spore-architect.md`
```markdown
---
name: spore-architect
description: Designs Spore's system from PRD/SPEC. Use for architecture decisions, data
  model, agent topology, n8n flows, and producing docs/ARCHITECTURE.md. Read-mostly.
tools: Read, Grep, Glob, WebSearch, WebFetch, Write
model: opus
---
You are Winston, the architect. Design from docs/PRD.md and docs/SPEC.md.
Enforce the four-layer separation: iOS (surface) / FastAPI+Claude (cognition) /
Obsidian (human layer) / Postgres+pgvector (machine state). n8n is transport only.
Deliverables go to docs/ARCHITECTURE.md: component diagram, data schema, agent topology,
API contracts, n8n flow list, and the confidence-gate routing logic. Propose; do not
implement. Flag every tradeoff with a recommendation and rationale.
```

### `.claude/agents/ios-engineer.md`
```markdown
---
name: ios-engineer
description: Builds the SwiftUI app and all capture surfaces — quick capture, Share Sheet
  extension, App Intents/Siri, widgets, voice, offline SwiftData queue, review UI,
  Live Activities. Use for any work under ios/.
tools: Read, Write, Edit, Bash, Glob, Grep
model: sonnet
skills: swiftui-screen
---
You are the iOS engineer. SwiftUI, iOS 17+. Capture must save on-device in <500ms and
work offline (SwiftData queue, sync on reconnect) — this is non-negotiable (NFR1/NFR6).
Use App Intents for Siri, WidgetKit for widgets, ActivityKit for Live Activities,
BackgroundTasks for sync. No API keys in the binary (NFR5) — talk only to the backend.
Write XCTest coverage for queue/sync logic. Match the acceptance criteria in the story verbatim.
```

### `.claude/agents/backend-engineer.md`
```markdown
---
name: backend-engineer
description: Builds FastAPI endpoints, Postgres/pgvector schema and migrations, Redis queue,
  Cloudflare Tunnel config, and n8n flow exports. Use for any work under backend/app/ or migrations/.
tools: Read, Write, Edit, Bash, Glob, Grep, mcp__postgres
model: sonnet
skills: fastapi-endpoint
---
You are the backend engineer. FastAPI + Postgres(pgvector/Timescale) + Redis.
HARD STOP and ask before running migrations. All capture endpoints are token-authed and
reachable only via Cloudflare Tunnel — no open inbound ports (NFR4). Implement the
confidence gate exactly per FR12. n8n calls your endpoints; it never holds logic.
pytest + contract tests on /capture and triage. Use the postgres MCP to inspect schema, not guess.
```

### `.claude/agents/agent-engineer.md`
```markdown
---
name: agent-engineer
description: Builds the RUNTIME Claude API agents (Director, Sorter, Scout, Builder, Curator)
  in backend/agents/ and the declarative skill loader that reads skills/*.skill.yaml.
tools: Read, Write, Edit, Bash, Glob, Grep
model: sonnet
---
You build Spore's runtime cognition (NOT Claude Code subagents). Each agent is a Python
module with a typed prompt + structured JSON output. Sorter returns the triage schema
(type/tags/domain/urgency/confidence/related_ids). Builder loads a skill file, runs its
prompt against a note, writes templated output. Cheap model for Sorter/dedup; stronger
model only for build-out. Log cost_usd per run. Batch triage on a cron. Validate all
JSON before it touches the DB or vault.
```

### `.claude/agents/qa-reviewer.md`
```markdown
---
name: qa-reviewer
description: Runs tests and reviews diffs against story acceptance criteria before merge.
  Use after any implementation story. Read + test execution only; does not modify source.
tools: Read, Grep, Glob, Bash
model: sonnet
---
You are QA. Run XCTest/pytest, verify each acceptance criterion explicitly (list AC → pass/fail),
check the confidence gate and offline-queue paths, and confirm no secrets leaked and no
unintended vault writes. Output a checklist verdict. Block merge on any failed AC.
```

### `.claude/agents/scrum-master.md`
```markdown
---
name: scrum-master
description: Shards a PRD epic into context-rich story files with embedded acceptance criteria
  and test notes. Use to turn docs/PRD.md epics into docs/stories/*.md before implementation.
tools: Read, Write, Glob, Grep
model: sonnet
skills: shard-epic
---
You are Bob, the Scrum Master (BMAD V6). Take one epic from docs/PRD.md and emit
docs/stories/<epic>.<story>.md files. Each story is self-contained: rationale, explicit
constraints, acceptance criteria copied verbatim, test plan, and links back to the PRD/SPEC.
One story = one mergeable unit. Do not implement.
```

---

## 6. Build-time skills (`.claude/skills/`)

### `.claude/skills/swiftui-screen/SKILL.md`
```markdown
---
name: swiftui-screen
description: Conventions for adding a SwiftUI screen to Spore — MVVM, navigation, SwiftData
  access, accessibility, and the standard preview + XCTest scaffold. Use when building any ios/ screen.
---
- MVVM: View + @Observable ViewModel; no business logic in views.
- Data via the shared SwiftData container; capture writes go through CaptureQueue (offline-safe).
- Every screen ships a #Preview and a ViewModel unit test.
- Respect Dynamic Type + VoiceOver labels. Haptics on review swipes.
```

### `.claude/skills/fastapi-endpoint/SKILL.md`
```markdown
---
name: fastapi-endpoint
description: Conventions for a Spore FastAPI endpoint — Pydantic schema, token auth dependency,
  service-layer separation, structured error envelope, and a pytest contract test. Use for any backend route.
---
- Router → service → repository. No DB calls in routers.
- Auth via the shared token dependency. Validate input with Pydantic; never trust client JSON.
- Return the standard {ok, data, error} envelope. Log structured events with a request id.
- Every endpoint gets a pytest contract test (happy path + auth failure + bad input).
```

### `.claude/skills/shard-epic/SKILL.md`
```markdown
---
name: shard-epic
description: BMAD V6 epic→story sharding format for Spore. Use when converting a PRD epic
  into individual story files.
---
Output one file per story: docs/stories/<epic>.<story>.md with sections —
Story (As a/I want/So that) · Acceptance Criteria (verbatim from PRD) · Constraints ·
Test Plan · Dependencies · Links (PRD/SPEC/ARCHITECTURE). One story = one PR.
```

---

## 7. Runtime skill registry (`skills/` — the product's own skills, FR21)

These are *data*, loaded by the runtime Builder agent — not Claude Code skills.

### `skills/expand_to_spec.skill.yaml`
```yaml
name: expand_to_spec
trigger: { on_promote_to: project, input_types: [project_idea] }
prompt: |
  Turn this idea note into a SPEC.md scaffold using the user's standard structure
  (Problem, Architecture, Data Model, Backlog). Pull in linked notes and Scout research.
output:
  template: templates/spec_scaffold.md
  path: "20_Projects/{{slug}}/SPEC.md"
post_actions:
  - create_folder: "20_Projects/{{slug}}"
  - set_idea_state: project
  - notify: telegram
```
(Plus `literature_note`, `decision_doc`, `atomic_split`, `merge_duplicates`, `daily_review`, `weekly_review` per SPEC §4.)

---

## 8. Slash commands (`.claude/commands/`)

### `.claude/commands/status.md`
```markdown
Read STATUS.md and docs/PRD.md. Summarize: what's done, what's in progress, blockers,
and the single next story to pick up. Do not write code.
```

### `.claude/commands/triage-run.md`
```markdown
Run the Sorter agent against the latest captures in the dev DB (read-only sandbox).
Show the structured JSON output and the routing decision for each. Write nothing to the vault.
```

### `.claude/commands/new-runtime-skill.md`
```markdown
Scaffold a new runtime skill file in skills/ from a name and description I provide.
Follow the schema in skills/expand_to_spec.skill.yaml. Add a matching output template stub.
```

### `.claude/commands/ship.md`
```markdown
Delegate to qa-reviewer to verify the current story's acceptance criteria and run tests.
If all AC pass, stage a conventional commit and show me the diff. HARD STOP before pushing.
```

---

## 9. Least-privilege tools matrix

| Subagent | Built-in tools | MCP | Model |
|---|---|---|---|
| spore-architect | Read, Grep, Glob, WebSearch, WebFetch, Write | — | opus |
| ios-engineer | Read, Write, Edit, Bash, Glob, Grep | — | sonnet |
| backend-engineer | Read, Write, Edit, Bash, Glob, Grep | postgres | sonnet |
| agent-engineer | Read, Write, Edit, Bash, Glob, Grep | — | sonnet |
| qa-reviewer | Read, Grep, Glob, Bash | — | sonnet |
| scrum-master | Read, Write, Glob, Grep | — | sonnet |

Principle: read-only agents (qa, architect) can't mutate source; only the three engineers get Write/Edit/Bash; only backend touches Postgres MCP.

---

## 10. Build sequence in Claude Code

```
# 0. Scaffold
cp docs/{PRD,SPEC}.md .  ;  drop this kit's files into .claude/  ;  git init

# 1. Architecture (read-mostly)
> Use spore-architect to produce docs/ARCHITECTURE.md from the PRD and SPEC.

# 2. Shard the first epics
> Use scrum-master to shard Epic 1 (Backend Spine) and Epic 2 (iOS Capture) into story files.

# 3. Implement bottom-up, story by story
> Use backend-engineer on story 1.1 (docker compose + data layer).   # HARD STOP before migrations
> Use backend-engineer on story 1.3 (/capture endpoint).
> Use ios-engineer on story 2.1–2.2 (app shell + offline capture queue).
> /ship                                                              # qa-reviewer gates the merge

# 4. Intelligence layer
> Use agent-engineer on Epic 3 (Sorter + embeddings + dedup).
> /triage-run                                                        # eyeball routing on real captures

# 5. Continue: Epic 4 (review queue) → 5 (vault) → 6 (skills) → 7 (pipeline) → 8 (resurface) → 9 (ops)
```

### Order rationale
Backend spine first (nothing works without capture+storage), then iOS capture (start dumping
real thoughts early), then triage (now you have data to triage), then the vault/skills/pipeline
layers. The runtime skill registry (`skills/`) gets populated during Epic 6 — that's where
build-time and runtime finally meet: the `expand_to_spec` runtime skill can hand a scaffolded
SPEC.md straight to your director-agent workflow.
```
