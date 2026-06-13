"""Contract tests for Epic 8 — resurfacing & reminders (Stories 8.1/8.2/8.3).

DB-backed tests follow the loop-local engine + get_session override pattern
from tests/test_pipeline.py. A SpyNotifier is injected via the
`_get_notifier` dependency override to assert delivery calls without hitting
APNs/Telegram/ntfy (the notifier seam, app.notify). The pure spaced-bucket
logic test at the bottom has no DB dependency.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import _to_async_dsn, get_database_url, get_session
from app.main import app
from app.models import Note, NoteLink, Reminder, ReviewItem
from app.notify import Notifier
from app.routers.internal import _get_notifier
from app.services.resurface_service import days_since_created, due_bucket, next_spaced_fire_at

TOKEN = os.environ.get("SPORE_CAPTURE_TOKEN", "dev-token")


class SpyNotifier:
    """Records every `send` call instead of delivering anything."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, channel: str, title: str, body: str, meta: dict | None = None) -> None:
        self.calls.append({"channel": channel, "title": title, "body": body, "meta": meta})


@pytest.fixture
async def db_sessionmaker():
    """Per-test async engine + sessionmaker, built inside the test's event loop."""
    engine = create_async_engine(_to_async_dsn(get_database_url()), future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def spy_notifier():
    return SpyNotifier()


@pytest.fixture
async def client(db_sessionmaker, spy_notifier):
    async def _override_get_session():
        async with db_sessionmaker() as session:
            yield session

    def _override_get_notifier() -> Notifier:
        return spy_notifier

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[_get_notifier] = _override_get_notifier
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(_get_notifier, None)


@pytest.fixture
async def cleanup(db_sessionmaker):
    """Tracks ids per-table; deletes them (in FK-safe order) after the test."""
    state = {
        "reminder": [],
        "review_item": [],
        "note_link": [],
        "note": [],
    }
    yield state
    async with db_sessionmaker() as session:
        if state["reminder"]:
            await session.execute(delete(Reminder).where(Reminder.id.in_(state["reminder"])))
        if state["review_item"]:
            await session.execute(delete(ReviewItem).where(ReviewItem.id.in_(state["review_item"])))
        if state["note_link"]:
            for src_id, dst_id, kind in state["note_link"]:
                await session.execute(
                    delete(NoteLink).where(
                        NoteLink.src_id == src_id,
                        NoteLink.dst_id == dst_id,
                        NoteLink.kind == kind,
                    )
                )
        if state["note"]:
            await session.execute(delete(Note).where(Note.id.in_(state["note"])))
        await session.commit()


async def _make_note(db_sessionmaker, cleanup, **fields) -> Note:
    async with db_sessionmaker() as session:
        note = Note(**fields)
        session.add(note)
        await session.flush()
        await session.commit()
        cleanup["note"].append(note.id)
        return note


async def _make_reminder(db_sessionmaker, cleanup, **fields) -> Reminder:
    async with db_sessionmaker() as session:
        reminder = Reminder(**fields)
        session.add(reminder)
        await session.flush()
        await session.commit()
        cleanup["reminder"].append(reminder.id)
        return reminder


async def _make_review_item(db_sessionmaker, cleanup, **fields) -> ReviewItem:
    async with db_sessionmaker() as session:
        item = ReviewItem(**fields)
        session.add(item)
        await session.flush()
        await session.commit()
        cleanup["review_item"].append(item.id)
        return item


async def _make_link(db_sessionmaker, cleanup, src_id, dst_id, kind="related") -> None:
    async with db_sessionmaker() as session:
        session.add(NoteLink(src_id=src_id, dst_id=dst_id, kind=kind))
        await session.flush()
        await session.commit()
        cleanup["note_link"].append((src_id, dst_id, kind))


async def _set_created_at(db_sessionmaker, note_id: uuid.UUID, created_at: datetime) -> None:
    async with db_sessionmaker() as session:
        note = await session.get(Note, note_id)
        note.created_at = created_at
        await session.commit()


def _auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# ── 8.1 — reminder-fire ─────────────────────────────────────────────────


async def test_reminder_fire_one_shot_due_fires_and_notifies(client, db_sessionmaker, cleanup, spy_notifier):
    now = datetime.now(timezone.utc)
    reminder = await _make_reminder(
        db_sessionmaker, cleanup,
        fire_at=now - timedelta(minutes=1), channel="apns", recurrence=None, status="scheduled",
    )

    response = await client.post("/internal/reminder-fire", headers=_auth())
    assert response.status_code == 200
    body = response.json()
    fired_ids = [r["id"] for r in body["data"]["reminders"]]
    assert str(reminder.id) in fired_ids
    assert any(c["channel"] == "apns" for c in spy_notifier.calls)

    async with db_sessionmaker() as session:
        row = await session.get(Reminder, reminder.id)
        assert row.status == "fired"


async def test_reminder_fire_daily_advances_and_stays_scheduled(client, db_sessionmaker, cleanup):
    now = datetime.now(timezone.utc)
    reminder = await _make_reminder(
        db_sessionmaker, cleanup,
        fire_at=now - timedelta(minutes=1), channel="apns", recurrence="daily", status="scheduled",
    )

    response = await client.post("/internal/reminder-fire", headers=_auth())
    assert response.status_code == 200

    async with db_sessionmaker() as session:
        row = await session.get(Reminder, reminder.id)
        assert row.status == "scheduled"
        new_fire_at = row.fire_at
        if new_fire_at.tzinfo is None:
            new_fire_at = new_fire_at.replace(tzinfo=timezone.utc)
        delta = new_fire_at - reminder.fire_at
        assert timedelta(hours=23) < delta < timedelta(hours=25)


async def test_reminder_fire_weekly_advances_seven_days(client, db_sessionmaker, cleanup):
    now = datetime.now(timezone.utc)
    reminder = await _make_reminder(
        db_sessionmaker, cleanup,
        fire_at=now - timedelta(minutes=1), channel="apns", recurrence="weekly", status="scheduled",
    )

    response = await client.post("/internal/reminder-fire", headers=_auth())
    assert response.status_code == 200

    async with db_sessionmaker() as session:
        row = await session.get(Reminder, reminder.id)
        assert row.status == "scheduled"
        new_fire_at = row.fire_at
        if new_fire_at.tzinfo is None:
            new_fire_at = new_fire_at.replace(tzinfo=timezone.utc)
        delta = new_fire_at - reminder.fire_at
        assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)


async def test_reminder_fire_spaced_advances_to_next_bucket(client, db_sessionmaker, cleanup):
    now = datetime.now(timezone.utc)
    reminder = await _make_reminder(
        db_sessionmaker, cleanup,
        fire_at=now - timedelta(minutes=1), channel="apns", recurrence="spaced", status="scheduled",
    )

    response = await client.post("/internal/reminder-fire", headers=_auth())
    assert response.status_code == 200

    async with db_sessionmaker() as session:
        row = await session.get(Reminder, reminder.id)
        assert row.status == "scheduled"
        new_fire_at = row.fire_at
        if new_fire_at.tzinfo is None:
            new_fire_at = new_fire_at.replace(tzinfo=timezone.utc)
        # default schedule [1,3,7,30] -> next bucket is +1 day from now.
        delta = new_fire_at - now
        assert timedelta(hours=23) < delta < timedelta(hours=25)


async def test_reminder_fire_future_reminder_untouched(client, db_sessionmaker, cleanup, spy_notifier):
    now = datetime.now(timezone.utc)
    reminder = await _make_reminder(
        db_sessionmaker, cleanup,
        fire_at=now + timedelta(days=1), channel="apns", recurrence=None, status="scheduled",
    )

    response = await client.post("/internal/reminder-fire", headers=_auth())
    assert response.status_code == 200
    fired_ids = [r["id"] for r in response.json()["data"]["reminders"]]
    assert str(reminder.id) not in fired_ids

    async with db_sessionmaker() as session:
        row = await session.get(Reminder, reminder.id)
        assert row.status == "scheduled"
    assert not any(c["meta"] and c["meta"].get("reminder_id") == str(reminder.id) for c in spy_notifier.calls)


# ── 8.2 — resurface ──────────────────────────────────────────────────────


async def test_resurface_three_day_old_note_is_due(client, db_sessionmaker, cleanup):
    now = datetime.now(timezone.utc)
    note = await _make_note(db_sessionmaker, cleanup, title="Three day note", type="fleeting", idea_state="seedling")
    await _set_created_at(db_sessionmaker, note.id, now - timedelta(days=3, hours=1))

    response = await client.get("/internal/resurface", headers=_auth())
    assert response.status_code == 200
    ids = [n["id"] for n in response.json()["data"]["notes"]]
    assert str(note.id) in ids


async def test_resurface_two_day_old_note_is_not_due(client, db_sessionmaker, cleanup):
    now = datetime.now(timezone.utc)
    note = await _make_note(db_sessionmaker, cleanup, title="Two day note", type="fleeting", idea_state="seedling")
    await _set_created_at(db_sessionmaker, note.id, now - timedelta(days=2, hours=1))

    response = await client.get("/internal/resurface", headers=_auth())
    assert response.status_code == 200
    ids = [n["id"] for n in response.json()["data"]["notes"]]
    assert str(note.id) not in ids


async def test_resurface_excludes_shipped_and_archived(client, db_sessionmaker, cleanup):
    now = datetime.now(timezone.utc)
    shipped = await _make_note(db_sessionmaker, cleanup, title="Shipped note", type="project_idea", idea_state="shipped")
    archived = await _make_note(db_sessionmaker, cleanup, title="Archived note", type="fleeting", idea_state="archived")
    await _set_created_at(db_sessionmaker, shipped.id, now - timedelta(days=3, hours=1))
    await _set_created_at(db_sessionmaker, archived.id, now - timedelta(days=3, hours=1))

    response = await client.get("/internal/resurface", headers=_auth())
    assert response.status_code == 200
    ids = [n["id"] for n in response.json()["data"]["notes"]]
    assert str(shipped.id) not in ids
    assert str(archived.id) not in ids


# ── 8.3 — digests ─────────────────────────────────────────────────────────


async def test_daily_digest_shape_and_notify(client, db_sessionmaker, cleanup, spy_notifier):
    now = datetime.now(timezone.utc)

    note = await _make_note(db_sessionmaker, cleanup, title="Resurface me", type="fleeting", idea_state="seedling")
    await _set_created_at(db_sessionmaker, note.id, now - timedelta(days=1, hours=1))

    open_item = await _make_review_item(db_sessionmaker, cleanup, status="open", reason="low_confidence")

    today_reminder = await _make_reminder(
        db_sessionmaker, cleanup,
        fire_at=now.replace(hour=12, minute=0, second=0, microsecond=0),
        channel="apns", recurrence=None, status="scheduled",
    )

    response = await client.get("/internal/digest/daily", headers=_auth())
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["review_queue_count"] >= 1
    reminder_ids = [r["id"] for r in data["todays_reminders"]]
    assert str(today_reminder.id) in reminder_ids
    assert data["resurfaced_idea"] is not None

    assert any(c["channel"] == "digest-daily" for c in spy_notifier.calls)
    # avoid unused-var warnings while documenting fixture usage
    assert open_item.status == "open"


async def test_weekly_digest_orphans_promotion_and_stale(client, db_sessionmaker, cleanup, spy_notifier):
    from app.config import settings

    orphan = await _make_note(db_sessionmaker, cleanup, title="Orphan note", type="fleeting", idea_state="seedling")
    linked_a = await _make_note(db_sessionmaker, cleanup, title="Linked A", type="fleeting", idea_state="seedling")
    linked_b = await _make_note(db_sessionmaker, cleanup, title="Linked B", type="fleeting", idea_state="seedling")
    await _make_link(db_sessionmaker, cleanup, linked_a.id, linked_b.id)

    # promotion_ready: a note with >= promote_ref_count incoming links and a
    # valid forward transition (seedling -> sapling).
    promo_target = await _make_note(db_sessionmaker, cleanup, title="Promo target", type="fleeting", idea_state="seedling")
    refs = [
        await _make_note(db_sessionmaker, cleanup, title=f"Ref {i}", type="fleeting", idea_state="seedling")
        for i in range(settings.promote_ref_count)
    ]
    for ref in refs:
        await _make_link(db_sessionmaker, cleanup, ref.id, promo_target.id)

    # stale: seedling whose updated_at is older than stale_days.
    stale_note = await _make_note(db_sessionmaker, cleanup, title="Stale note", type="fleeting", idea_state="seedling")
    async with db_sessionmaker() as session:
        row = await session.get(Note, stale_note.id)
        row.updated_at = datetime.now(timezone.utc) - timedelta(days=settings.stale_days + 1)
        await session.commit()

    response = await client.get("/internal/digest/weekly", headers=_auth())
    assert response.status_code == 200
    data = response.json()["data"]

    orphan_ids = [n["id"] for n in data["orphan_notes"]]
    assert str(orphan.id) in orphan_ids
    assert str(linked_a.id) not in orphan_ids
    assert str(linked_b.id) not in orphan_ids

    promo_ids = [p["note_id"] for p in data["promotion_ready"]]
    assert str(promo_target.id) in promo_ids

    stale_ids = [s["note_id"] for s in data["stale"]]
    assert str(stale_note.id) in stale_ids

    assert any(c["channel"] == "digest-weekly" for c in spy_notifier.calls)


# ── auth ─────────────────────────────────────────────────────────────────


async def test_reminder_fire_missing_token_returns_401(client):
    response = await client.post("/internal/reminder-fire")
    assert response.status_code == 401


async def test_resurface_missing_token_returns_401(client):
    response = await client.get("/internal/resurface")
    assert response.status_code == 401


async def test_daily_digest_missing_token_returns_401(client):
    response = await client.get("/internal/digest/daily")
    assert response.status_code == 401


async def test_weekly_digest_missing_token_returns_401(client):
    response = await client.get("/internal/digest/weekly")
    assert response.status_code == 401


# ── pure unit tests — spaced-bucket logic (no DB) ──────────────────────────


def test_days_since_created_floors_to_whole_days():
    note = type("N", (), {"created_at": datetime.now(timezone.utc) - timedelta(days=3, hours=5)})()
    assert days_since_created(note) == 3


def test_due_bucket_matches_schedule():
    assert due_bucket(3, [1, 3, 7, 30]) == 3
    assert due_bucket(2, [1, 3, 7, 30]) is None
    assert due_bucket(30, [1, 3, 7, 30]) == 30


def test_next_spaced_fire_at_uses_smallest_bucket():
    now = datetime.now(timezone.utc)
    next_fire = next_spaced_fire_at(now, [1, 3, 7, 30])
    assert next_fire - now == timedelta(days=1)


def test_next_spaced_fire_at_empty_schedule_defaults_to_one_day():
    now = datetime.now(timezone.utc)
    next_fire = next_spaced_fire_at(now, [])
    assert next_fire - now == timedelta(days=1)
