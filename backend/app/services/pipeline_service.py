"""Service layer for the idea pipeline / state machine (Epic 7).

Stories:
  7.1 — `list_by_state` (GET /pipeline) and `move` (POST /pipeline/{id}/move),
        enforcing `app.pipeline.ALLOWED_TRANSITIONS` and logging an
        `idea_event` row for every transition.
  7.3 — `promotion_suggestions`: notes with >= settings.promote_ref_count
        incoming `note_link` references and a valid forward transition are
        suggested for promotion to `next_forward_state`.
  7.4 — `find_stale_seedlings`: 'seedling' notes whose `updated_at` is older
        than settings.stale_days. Reused by GET /pipeline/suggestions and
        POST /internal/stale-sweep. Surfacing only — no auto-mutation.

Routers call into this module; all DB access goes through the repositories.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Note
from app.pipeline import ALL_STATES, can_transition, next_forward_state
from app.repositories.idea_event import IdeaEventRepository
from app.repositories.note import NoteRepository


class NoteNotFound(Exception):
    """No note with the given id."""


class InvalidTransition(Exception):
    """`from_state -> to_state` is not an allowed pipeline transition."""

    def __init__(self, from_state: str | None, to_state: str):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"cannot transition from {from_state!r} to {to_state!r}")


async def list_by_state(session: AsyncSession, limit_per_state: int = 200) -> dict:
    """Return notes grouped by idea_state, plus per-state counts.

    Shape: {"states": {state: [note, ...], ...}, "counts": {state: int, ...}}
    """
    notes = NoteRepository(session)
    states: dict[str, list[Note]] = {}
    counts: dict[str, int] = {}
    for state in ALL_STATES:
        rows = await notes.list_by_state(state, limit=limit_per_state)
        states[state] = rows
        counts[state] = len(rows)
    return {"states": states, "counts": counts}


async def move(
    session: AsyncSession,
    note_id: uuid.UUID,
    to_state: str,
    reason: str = "manual",
) -> Note:
    """Transition `note_id` to `to_state`.

    Raises NoteNotFound (404) or InvalidTransition (409); the router maps
    these to HTTP responses. On success, persists the new idea_state, bumps
    updated_at, and logs an idea_event row.
    """
    notes = NoteRepository(session)
    note = await notes.get(note_id)
    if note is None:
        raise NoteNotFound(str(note_id))

    from_state = note.idea_state
    if not can_transition(from_state, to_state):
        raise InvalidTransition(from_state, to_state)

    now = datetime.now(timezone.utc)
    note.idea_state = to_state
    note.updated_at = now
    await session.flush()

    events = IdeaEventRepository(session)
    await events.create(note_id=note.id, to_state=to_state, from_state=from_state, reason=reason)

    return note


async def promotion_suggestions(session: AsyncSession) -> list[dict]:
    """Notes with >= settings.promote_ref_count incoming note_link refs and
    a valid forward transition (i.e. not shipped/archived)."""
    notes = NoteRepository(session)
    ref_counts = await notes.incoming_link_counts(settings.promote_ref_count)

    suggestions: list[dict] = []
    for note_id, ref_count in ref_counts.items():
        note = await notes.get(note_id)
        if note is None:
            continue
        suggested = next_forward_state(note.idea_state)
        if suggested is None:
            continue
        suggestions.append(
            {
                "note_id": note.id,
                "title": note.title,
                "ref_count": ref_count,
                "current_state": note.idea_state,
                "suggested_state": suggested,
            }
        )
    return suggestions


async def find_stale_seedlings(session: AsyncSession) -> list[Note]:
    """Return 'seedling' notes whose `updated_at` is older than settings.stale_days."""
    notes = NoteRepository(session)
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.stale_days)
    return await notes.list_stale_seedlings(cutoff)


async def stale_seedling_suggestions(session: AsyncSession) -> list[dict]:
    """`find_stale_seedlings` shaped for the GET /pipeline/suggestions response."""
    now = datetime.now(timezone.utc)
    stale = await find_stale_seedlings(session)
    result: list[dict] = []
    for note in stale:
        updated_at = note.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age_days = (now - updated_at).days
        result.append(
            {
                "note_id": note.id,
                "title": note.title,
                "age_days": age_days,
                "suggested_actions": ["promote", "merge", "archive"],
            }
        )
    return result


async def suggestions(session: AsyncSession) -> dict:
    """Combined payload for GET /pipeline/suggestions (Stories 7.3 + 7.4)."""
    return {
        "promotions": await promotion_suggestions(session),
        "stale": await stale_seedling_suggestions(session),
    }
