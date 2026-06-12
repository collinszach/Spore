"""Builder runtime (Epic 6, Story 6.2 — SPEC.md §2.5 / §4).

`run_skill` is the single entry point: given a loaded `Skill` (Story 6.1)
and a `Note`, it

1. builds a Builder prompt from `skill.prompt` + the note's title/type/body
   + any linked-note context (same `note_link` pattern as
   `agents.triage` / `app.vault_adapter`),
2. calls Claude with the **build-out model** (`settings.builder_model` —
   "stronger model only for build-out", CLAUDE.md rule 7) and treats the
   response as free-form prose/Markdown (NOT the Sorter's strict-JSON
   shape),
3. renders `skill.output.template` (if any) with `{{var}}` substitution and
   resolves `skill.output.path`,
4. writes the rendered content to the vault via
   `VaultWriter.write_raw(rel_path, content, commit_message)`,
5. applies `skill.post_actions` (`create_folder`, `set_idea_state`,
   `notify` — unknown actions are ignored),
6. logs one `skill_run` row (cost ledger, CLAUDE.md rule 7).

Returns a summary dict: `{skill, note_id, output_path, status}`.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.clients import ClaudeClient
from agents.skills_registry import Skill
from app.config import settings
from app.models import Note, NoteLink
from app.repositories.idea_event import IdeaEventRepository
from app.repositories.note import NoteRepository
from app.repositories.skill_run import SkillRunRepository
from app.vault import VaultWriter, slugify

logger = logging.getLogger("spore")

# Per-million-token pricing (USD) for known Builder models. Unknown models
# (including fake clients) cost $0 — cost discipline (CLAUDE.md rule 7) only
# applies to real API calls. Mirrors agents.triage._MODEL_PRICING_PER_MTOK.
_MODEL_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    # (input $/Mtok, output $/Mtok)
    "claude-sonnet-4-6": (3.00, 15.00),
}


def _estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    pricing = _MODEL_PRICING_PER_MTOK.get(model)
    if pricing is None:
        return Decimal("0")
    in_price, out_price = pricing
    cost = (tokens_in / 1_000_000) * in_price + (tokens_out / 1_000_000) * out_price
    return Decimal(str(round(cost, 5)))


# ── Prompt construction ──────────────────────────────────────────────────


async def _linked_note_context(session: AsyncSession, note: Note) -> str:
    """Render a short Markdown block describing notes linked from `note`
    (same `note_link` table the vault writer uses for backlinks)."""
    stmt = select(NoteLink).where(NoteLink.src_id == note.id)
    result = await session.execute(stmt)
    links = list(result.scalars().all())

    if not links:
        return "(none)"

    lines: list[str] = []
    for link in links:
        related = await session.get(Note, link.dst_id)
        if related is None:
            continue
        title = related.title or str(related.id)
        lines.append(f"- [{link.kind}] {title} (type={related.type}, id={related.id})")

    return "\n".join(lines) if lines else "(none)"


async def _build_prompt(session: AsyncSession, skill: Skill, note: Note, body: str) -> tuple[str, str]:
    system = (
        "You are Builder, the build-out subagent for Spore. Given a skill "
        "instruction and a note, produce the build-out content the skill "
        "describes. Respond with the content itself (Markdown/prose) — no "
        "preamble, no code fences, no meta-commentary about what you're "
        "doing."
    )

    linked = await _linked_note_context(session, note)

    user = (
        f"Skill instructions:\n{skill.prompt.strip()}\n\n"
        f"Note title: {note.title or '(untitled)'}\n"
        f"Note type: {note.type or '(unknown)'}\n"
        f"Note domain: {note.domain or '(none)'}\n\n"
        f"Note body:\n{body}\n\n"
        f"Linked notes:\n{linked}\n\n"
        "Produce the build-out content now."
    )
    return system, user


# ── Template / var substitution ──────────────────────────────────────────

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def _render(text: str, variables: dict[str, str]) -> str:
    """Substitute `{{var}}` placeholders. Unknown vars are left as-is."""

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))

    return _VAR_RE.sub(_sub, text)


def _build_vars(note: Note, body: str, content: str) -> dict[str, str]:
    title = note.title or "untitled"
    slug = slugify(title)
    return {
        "title": title,
        "slug": slug,
        "date": datetime.now(timezone.utc).date().isoformat(),
        "body": body,
        "domain": note.domain or "",
        "content": content,
    }


# ── Post actions ─────────────────────────────────────────────────────────


async def _apply_post_actions(
    session: AsyncSession,
    skill: Skill,
    note: Note,
    variables: dict[str, str],
    *,
    vault_writer: VaultWriter,
) -> None:
    note_repo = NoteRepository(session)
    idea_event_repo = IdeaEventRepository(session)

    for action in skill.post_actions:
        if not isinstance(action, dict) or not action:
            continue
        # Each post_action is a single-key dict, e.g. {"create_folder": "..."}.
        for key, value in action.items():
            if key == "create_folder":
                rel_folder = _render(str(value), variables)
                await _ensure_folder(vault_writer, rel_folder)
            elif key == "set_idea_state":
                new_state = _render(str(value), variables)
                old_state = note.idea_state
                if old_state != new_state:
                    await note_repo.update(note.id, idea_state=new_state)
                    await idea_event_repo.create(
                        note_id=note.id,
                        from_state=old_state,
                        to_state=new_state,
                        reason="skill",
                    )
            elif key == "notify":
                logger.info(
                    "skill_notify",
                    extra={"skill": skill.name, "note_id": str(note.id), "channel": value},
                )
            else:
                logger.warning(
                    "skill_unknown_post_action",
                    extra={"skill": skill.name, "action": key},
                )


async def _ensure_folder(vault_writer: VaultWriter, rel_folder: str) -> None:
    """Ensure `rel_folder` exists under the vault base by writing a
    placeholder `.gitkeep` (only `GitVaultWriter` has a real filesystem;
    `NoOpVaultWriter.write_raw` no-ops)."""
    rel_path = f"{rel_folder.rstrip('/')}/.gitkeep"
    write_raw = getattr(vault_writer, "write_raw", None)
    if write_raw is None:
        return

    # Skip if it already exists (avoid an empty extra commit on rerun).
    base_path = getattr(vault_writer, "base_path", None)
    if base_path is not None:
        abs_path = Path(base_path) / rel_path
        if abs_path.exists():
            return

    await vault_writer.write_raw(rel_path, "", f"skill: ensure folder {rel_folder}")


# ── Main entry point ────────────────────────────────────────────────────


async def run_skill(
    session: AsyncSession,
    skill: Skill,
    note: Note,
    *,
    claude: ClaudeClient,
    vault_writer: VaultWriter,
) -> dict:
    """Run `skill` against `note`. Returns `{skill, note_id, output_path, status}`."""
    skill_run_repo = SkillRunRepository(session)

    body = _note_body(note)

    try:
        system, user = await _build_prompt(session, skill, note, body)
        response = await claude.complete(system, user)

        content = response.text.strip()
        variables = _build_vars(note, body, content)

        rendered = _render_output(skill, variables)
        output_rel_path = _render(skill.output.path, variables)
        output_rel_path = output_rel_path.lstrip("/")

        await vault_writer.write_raw(
            output_rel_path,
            rendered,
            commit_message=f"skill: {skill.name} -> {output_rel_path}",
        )

        await _apply_post_actions(session, skill, note, variables, vault_writer=vault_writer)

        status = "ok"
    except Exception:
        logger.exception("skill_run_failed", extra={"skill": skill.name, "note_id": str(note.id)})
        await skill_run_repo.create(
            skill=skill.name,
            note_id=note.id,
            status="error",
            model=getattr(claude, "model", None),
        )
        return {"skill": skill.name, "note_id": note.id, "output_path": None, "status": "error"}

    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens
    model = response.model
    cost_usd = _estimate_cost_usd(model, tokens_in, tokens_out)

    await skill_run_repo.create(
        skill=skill.name,
        note_id=note.id,
        status=status,
        output_path=output_rel_path,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )

    return {
        "skill": skill.name,
        "note_id": note.id,
        "output_path": output_rel_path,
        "status": status,
    }


def _note_body(note: Note) -> str:
    """Best-effort body text for a note. The ORM `Note` row has no body
    column (prose lives in the vault) — use the title as a minimal stand-in
    when nothing richer is available."""
    return note.title or ""


def _render_output(skill: Skill, variables: dict[str, str]) -> str:
    template_rel = skill.output.template
    if not template_rel:
        return _render(variables["content"], variables)

    template_path = Path(settings.skills_dir) / template_rel
    template_text = template_path.read_text(encoding="utf-8")
    return _render(template_text, variables)
