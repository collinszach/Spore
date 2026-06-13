"""Tests for Epic 9 — cost dashboard (9.1), ops metrics (9.3), and the
corrections feedback loop (9.2, FR37).

DB-backed tests follow the loop-local engine + get_session dependency
override pattern from tests/test_capture.py / tests/test_triage.py. The
PM runs these against the remote Postgres test DB; the few-shot prompt
tests are pure (no DB / no network) and run anywhere.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agents.clients import ClaudeResponse, ClaudeUsage
from agents.feedback import format_fewshot_block, recent_correction_examples
from agents.sorter import _build_prompt
from app.config import settings
from app.db import _to_async_dsn, get_database_url, get_session
from app.main import app
from app.models import Correction, Note, RawCapture, Reminder, ReviewItem, SkillRun


@pytest.fixture
async def db_session_factory():
    engine = create_async_engine(_to_async_dsn(get_database_url()), future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def client(db_session_factory):
    """Async ASGI client with get_session overridden to a loop-local session
    factory (single event loop — asyncpg connections can't cross loops)."""
    from httpx import ASGITransport, AsyncClient

    async def _override_get_session():
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)


def _auth_headers():
    return {"X-Spore-Token": settings.spore_capture_token}


# ── 9.1 Cost dashboard ──────────────────────────────────────────────────


@pytest.fixture
async def cleanup_skill_runs(db_session_factory):
    tracked: list[uuid.UUID] = []
    yield tracked
    async with db_session_factory() as session:
        if tracked:
            await session.execute(delete(SkillRun).where(SkillRun.id.in_(tracked)))
            await session.commit()


async def test_cost_dashboard_aggregates(db_session_factory, client, cleanup_skill_runs):
    now = datetime.now(timezone.utc)

    rows = [
        # skill, model, tokens_in, tokens_out, cost, created_at
        ("sorter", "claude-haiku-4-5-20251001", 100, 50, "0.00100", now),
        ("sorter", "claude-haiku-4-5-20251001", 200, 100, "0.00200", now - timedelta(days=1)),
        ("builder", "claude-sonnet-4-6", 500, 300, "0.01000", now - timedelta(days=10)),
    ]

    async with db_session_factory() as session:
        for skill, model, tin, tout, cost, created_at in rows:
            run = SkillRun(
                skill=skill,
                status="ok",
                model=model,
                tokens_in=tin,
                tokens_out=tout,
                cost_usd=Decimal(cost),
                created_at=created_at,
            )
            session.add(run)
            await session.flush()
            cleanup_skill_runs.append(run.id)
        await session.commit()

    response = await client.get("/internal/cost", headers=_auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    data = body["data"]

    total = Decimal("0.00100") + Decimal("0.00200") + Decimal("0.01000")
    assert Decimal(str(data["total_usd"])) >= Decimal("0.01300") - Decimal("0.00001")
    # this_week should include the two recent rows but not the 10-day-old one.
    this_week = Decimal("0.00100") + Decimal("0.00200")
    assert Decimal(str(data["this_week_usd"])) >= this_week - Decimal("0.00001")
    assert Decimal(str(data["this_week_usd"])) < total

    by_skill = {row["skill"]: row for row in data["by_skill"]}
    assert by_skill["sorter"]["runs"] >= 2
    assert by_skill["sorter"]["tokens_in"] >= 300
    assert by_skill["builder"]["runs"] >= 1

    by_model = {row["model"]: row for row in data["by_model"]}
    assert by_model["claude-haiku-4-5-20251001"]["runs"] >= 2
    assert by_model["claude-sonnet-4-6"]["runs"] >= 1

    assert isinstance(data["by_day"], list)
    days = [row["day"] for row in data["by_day"]]
    assert days == sorted(days)


# ── 9.3 Ops metrics ─────────────────────────────────────────────────────


@pytest.fixture
async def cleanup_metrics_rows(db_session_factory):
    tracked: dict[str, list[uuid.UUID]] = {
        "captures": [],
        "notes": [],
        "review_items": [],
        "reminders": [],
    }
    yield tracked
    async with db_session_factory() as session:
        if tracked["reminders"]:
            await session.execute(delete(Reminder).where(Reminder.id.in_(tracked["reminders"])))
        if tracked["review_items"]:
            await session.execute(delete(ReviewItem).where(ReviewItem.id.in_(tracked["review_items"])))
        if tracked["notes"]:
            await session.execute(delete(Note).where(Note.id.in_(tracked["notes"])))
        if tracked["captures"]:
            await session.execute(delete(RawCapture).where(RawCapture.id.in_(tracked["captures"])))
        await session.commit()


async def test_ops_metrics_counts_and_gate_distribution(db_session_factory, client, cleanup_metrics_rows):
    async with db_session_factory() as session:
        # Captures: one pending, one triaged.
        cap_pending = RawCapture(source="ios_quick", body="pending capture", status="pending")
        cap_triaged = RawCapture(source="ios_quick", body="triaged capture", status="triaged")
        session.add_all([cap_pending, cap_triaged])
        await session.flush()
        cleanup_metrics_rows["captures"].extend([cap_pending.id, cap_triaged.id])

        # Notes: one direct-write (no needs-review tag), one needs-review.
        note_direct = Note(
            title="direct note",
            type="fleeting",
            tags=["foo"],
            idea_state="seedling",
            source_capture_id=cap_triaged.id,
        )
        note_review = Note(
            title="needs review note",
            type="fleeting",
            tags=["needs-review"],
            idea_state="seedling",
        )
        session.add_all([note_direct, note_review])
        await session.flush()
        cleanup_metrics_rows["notes"].extend([note_direct.id, note_review.id])

        # review_item: open, reason=low_confidence, capture has no note ->
        # counts toward review_floor.
        floor_capture = RawCapture(source="ios_quick", body="floor capture", status="triaged")
        session.add(floor_capture)
        await session.flush()
        cleanup_metrics_rows["captures"].append(floor_capture.id)

        review_floor_item = ReviewItem(
            capture_id=floor_capture.id, reason="low_confidence", status="open"
        )
        session.add(review_floor_item)
        await session.flush()
        cleanup_metrics_rows["review_items"].append(review_floor_item.id)

        # reminder: scheduled.
        reminder = Reminder(
            note_id=note_direct.id,
            fire_at=datetime.now(timezone.utc) + timedelta(hours=1),
            status="scheduled",
        )
        session.add(reminder)
        await session.flush()
        cleanup_metrics_rows["reminders"].append(reminder.id)

        await session.commit()

    response = await client.get("/internal/metrics", headers=_auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    data = body["data"]

    assert data["captures_by_status"].get("pending", 0) >= 1
    assert data["captures_by_status"].get("triaged", 0) >= 2

    gate = data["gate_distribution"]
    assert gate["needs_review"] >= 1
    assert gate["review_floor"] >= 1
    assert gate["direct_write"] >= 1

    assert data["review_queue_depth"] >= 1
    assert data["notes_by_idea_state"].get("seedling", 0) >= 2
    assert data["reminders_scheduled"] >= 1
    assert isinstance(data["cost_today_usd"], (int, float))
    assert isinstance(data["captures_today"], int)


# ── 9.2 Corrections feedback ───────────────────────────────────────────


@pytest.fixture
async def cleanup_corrections(db_session_factory):
    tracked: list[uuid.UUID] = []
    yield tracked
    async with db_session_factory() as session:
        if tracked:
            await session.execute(delete(Correction).where(Correction.id.in_(tracked)))
            await session.commit()


async def test_corrections_summary_and_recent_examples(db_session_factory, client, cleanup_corrections):
    now = datetime.now(timezone.utc)
    async with db_session_factory() as session:
        examples = [
            ({"type": "fleeting", "tags": []}, {"type": "task", "tags": ["urgent"]}, now - timedelta(minutes=2)),
            ({"type": "reference", "tags": []}, {"type": "project_idea", "tags": ["spore"]}, now - timedelta(minutes=1)),
            ({"type": "journal", "tags": []}, {"type": "fleeting", "tags": []}, now),
        ]
        for original, corrected, created_at in examples:
            row = Correction(original_json=original, corrected_json=corrected, created_at=created_at)
            session.add(row)
            await session.flush()
            cleanup_corrections.append(row.id)
        await session.commit()

    response = await client.get("/internal/corrections/summary?k=2", headers=_auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    data = body["data"]

    assert data["count"] >= 3
    assert len(data["recent"]) == 2
    # newest first
    assert data["recent"][0]["corrected_json"]["type"] == "fleeting"
    assert data["recent"][1]["corrected_json"]["type"] == "project_idea"

    # feedback.recent_correction_examples directly
    async with db_session_factory() as session:
        recent = await recent_correction_examples(session, k=2)
    assert len(recent) == 2
    assert recent[0]["corrected"]["type"] == "fleeting"
    assert recent[1]["corrected"]["type"] == "project_idea"


# ── Sorter few-shot gating (pure, no DB / no network) ───────────────────


def test_format_fewshot_block_renders_examples():
    examples = [
        {"original": {"type": "fleeting", "tags": []}, "corrected": {"type": "task", "tags": ["urgent"]}},
    ]
    block = format_fewshot_block(examples)
    assert "Recent corrections to learn from:" in block
    assert "task" in block
    assert "urgent" in block


def test_format_fewshot_block_empty_for_no_examples():
    assert format_fewshot_block([]) == ""


def test_build_prompt_includes_fewshot_block_when_provided():
    capture = RawCapture(id=uuid.uuid4(), source="ios_quick", body="a thought")
    block = "Recent corrections to learn from:\n- was: type='fleeting' -> corrected to: type='task'"

    _system, user_with = _build_prompt(capture, [], fewshot_block=block)
    _system, user_without = _build_prompt(capture, [], fewshot_block=None)

    assert "Recent corrections to learn from:" in user_with
    assert "Recent corrections to learn from:" not in user_without


# ── Auth ─────────────────────────────────────────────────────────────────


def test_cost_metrics_corrections_require_auth():
    from fastapi.testclient import TestClient

    client = TestClient(app)

    assert client.get("/internal/cost").status_code == 401
    assert client.get("/internal/metrics").status_code == 401
    assert client.get("/internal/corrections/summary").status_code == 401
