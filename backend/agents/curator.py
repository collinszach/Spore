"""Curator — resurfacing digests (Story 8.3, FR32/FR33).

Assembles daily/weekly digest payloads from the DB. By default this is pure
structured aggregation (CLAUDE.md rule 7: Curator = $0 unless opted in).
When `settings.curator_narrative_enabled` is True, an optional one-line
narrative is generated via `agents.clients.get_claude_client(model=
settings.curator_model)` (cheap model) and a `skill_run` row with
skill='curator' is logged.

`daily_digest` / `weekly_digest` are pure-DB assembly functions; the
`/internal/digest/*` router calls `notifier.send(...)` separately so tests
can inject a SpyNotifier without mocking this module.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from agents.clients import get_claude_client
from app.config import settings
from app.repositories.note import NoteRepository
from app.repositories.reminder import ReminderRepository
from app.repositories.review import ReviewRepository
from app.repositories.skill_run import SkillRunRepository
from app.services import pipeline_service
from app.services.resurface_service import resurface_due_notes


async def _narrative(prompt: str) -> str | None:
    """Optional one-line narrative via the cheap Curator model (gated, logs skill_run)."""
    if not settings.curator_narrative_enabled:
        return None

    claude = get_claude_client(model=settings.curator_model)
    response = await claude.complete(
        system="You are Curator, Spore's resurfacing assistant. Reply with exactly one short, "
        "encouraging sentence summarizing the digest below. No markdown, no preamble.",
        user=prompt,
    )
    return response.text.strip()


async def daily_digest(session: AsyncSession, now: datetime | None = None) -> dict:
    """Assemble GET /internal/digest/daily payload (Story 8.3).

    {review_queue_count, todays_reminders, resurfaced_idea, narrative?}
    """
    now = now or datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    reviews = ReviewRepository(session)
    reminders = ReminderRepository(session)

    review_queue_count = await reviews.count_by_status("open")
    todays_reminders = await reminders.list_due_today(day_start, day_end)
    resurfaced = await resurface_due_notes(session, now)
    resurfaced_idea = resurfaced[0] if resurfaced else None

    payload: dict = {
        "review_queue_count": review_queue_count,
        "todays_reminders": [
            {
                "id": r.id,
                "note_id": r.note_id,
                "fire_at": r.fire_at,
                "channel": r.channel,
                "recurrence": r.recurrence,
            }
            for r in todays_reminders
        ],
        "resurfaced_idea": resurfaced_idea,
    }

    narrative = await _narrative(
        f"review_queue_count={review_queue_count}, "
        f"todays_reminders={len(todays_reminders)}, "
        f"resurfaced_idea={resurfaced_idea['title'] if resurfaced_idea else None}"
    )
    if narrative is not None:
        payload["narrative"] = narrative
        skill_runs = SkillRunRepository(session)
        await skill_runs.create(skill="curator", status="ok", model=settings.curator_model)

    return payload


async def weekly_digest(session: AsyncSession, now: datetime | None = None) -> dict:
    """Assemble GET /internal/digest/weekly payload (Story 8.3).

    {orphan_notes, dangling_links, promotion_ready, stale, narrative?}
    """
    now = now or datetime.now(timezone.utc)
    notes = NoteRepository(session)

    orphan_notes = await notes.list_orphans()
    dangling_links = await notes.list_dangling_links()
    promotion_ready = await pipeline_service.promotion_suggestions(session)
    stale = await pipeline_service.stale_seedling_suggestions(session)

    payload: dict = {
        "orphan_notes": [
            {"id": n.id, "title": n.title, "type": n.type, "idea_state": n.idea_state}
            for n in orphan_notes
        ],
        "dangling_links": [
            {"src_id": link.src_id, "dst_id": link.dst_id, "kind": link.kind}
            for link in dangling_links
        ],
        "promotion_ready": promotion_ready,
        "stale": stale,
    }

    narrative = await _narrative(
        f"orphan_notes={len(orphan_notes)}, dangling_links={len(dangling_links)}, "
        f"promotion_ready={len(promotion_ready)}, stale={len(stale)}"
    )
    if narrative is not None:
        payload["narrative"] = narrative
        skill_runs = SkillRunRepository(session)
        await skill_runs.create(skill="curator", status="ok", model=settings.curator_model)

    return payload
