"""Service layer for Epic 8 — reminder-fire (8.1) and spaced resurfacing (8.2).

Stories:
  8.1 — `fire_due_reminders`: select scheduled reminders with `fire_at <=
        now`, notify, then advance/close per `recurrence`
        (null|daily|weekly|spaced). Idempotent — a non-due reminder is
        never touched.
  8.2 — `resurface_due_notes` / `days_since_created` / `due_bucket`: a note
        is "due to resurface" when floor(days since `note.created_at`)
        equals one of `settings.resurface_schedule_days`, and its
        idea_state is not shipped/archived.

`due_bucket` / `days_since_created` are pure functions (no DB/IO) so they
can be unit-tested in isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Note, Reminder
from app.notify import Notifier
from app.repositories.note import NoteRepository
from app.repositories.reminder import ReminderRepository


def _ensure_aware(dt: datetime) -> datetime:
    """Treat naive timestamps (e.g. from a test DB) as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def days_since_created(note: Note, now: datetime | None = None) -> int:
    """Whole days elapsed since `note.created_at` (floor)."""
    now = now or datetime.now(timezone.utc)
    created_at = _ensure_aware(note.created_at)
    delta = now - created_at
    return delta.days


def due_bucket(days: int, schedule: list[int] | None = None) -> int | None:
    """Return `days` if it's in the resurface schedule, else None.

    Pure function — Story 8.2's "due to resurface" rule.
    """
    schedule = schedule if schedule is not None else settings.resurface_schedule_days
    return days if days in schedule else None


def next_spaced_fire_at(now: datetime, schedule: list[int] | None = None) -> datetime:
    """Next fire_at for a `spaced` reminder, measured from `now` (Story 8.1).

    Uses the smallest bucket in the spaced schedule (e.g. schedule [1,3,7,30]
    -> +1 day). Falls back to +1 day if the schedule is empty.
    """
    schedule = schedule if schedule is not None else settings.resurface_schedule_days
    step_days = min(schedule) if schedule else 1
    return now + timedelta(days=step_days)


async def fire_due_reminders(
    session: AsyncSession,
    notifier: Notifier,
    now: datetime | None = None,
) -> list[Reminder]:
    """Fire all due (`status='scheduled'`, `fire_at <= now`) reminders (Story 8.1).

    For each due reminder: call `notifier.send`, then per `recurrence`:
      - None        -> status='fired'
      - 'daily'      -> fire_at += 1 day, stays 'scheduled'
      - 'weekly'     -> fire_at += 7 days, stays 'scheduled'
      - 'spaced'     -> fire_at = next_spaced_fire_at(now), stays 'scheduled'

    Returns the list of reminders that fired (with updated fields applied).
    Idempotent: reminders with `fire_at > now` are never selected/advanced.
    """
    now = now or datetime.now(timezone.utc)
    reminders = ReminderRepository(session)

    due = await reminders.list_due(now)
    fired: list[Reminder] = []

    for reminder in due:
        await notifier.send(
            channel=reminder.channel,
            title="Spore reminder",
            body=f"Reminder for note {reminder.note_id}" if reminder.note_id else "Spore reminder",
            meta={"reminder_id": str(reminder.id), "note_id": str(reminder.note_id) if reminder.note_id else None},
        )

        if reminder.recurrence == "daily":
            await reminders.update(reminder.id, fire_at=reminder.fire_at + timedelta(days=1))
        elif reminder.recurrence == "weekly":
            await reminders.update(reminder.id, fire_at=reminder.fire_at + timedelta(days=7))
        elif reminder.recurrence == "spaced":
            await reminders.update(reminder.id, fire_at=next_spaced_fire_at(now))
        else:
            await reminders.update(reminder.id, status="fired")

        fired.append(reminder)

    if fired:
        await session.commit()

    return fired


async def resurface_due_notes(session: AsyncSession, now: datetime | None = None) -> list[dict]:
    """Return active notes whose age (in whole days) matches a resurface bucket (Story 8.2).

    Pure read — no state column needed. Excludes shipped/archived notes.
    """
    now = now or datetime.now(timezone.utc)
    notes = NoteRepository(session)
    schedule = settings.resurface_schedule_days

    due: list[dict] = []
    for note in await notes.list_active():
        days = days_since_created(note, now)
        bucket = due_bucket(days, schedule)
        if bucket is not None:
            due.append(
                {
                    "id": note.id,
                    "title": note.title,
                    "type": note.type,
                    "days_since": days,
                    "bucket": bucket,
                }
            )
    return due
