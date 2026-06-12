"""Tests for the Epic 3 triage pipeline (Sorter + embeddings + dedup + gate).

Pure tests (Sorter validation, gate decision table) run with no DB and no
network — they're the ones the agent-engineer can run locally. The dedup and
`triage_batch` integration tests need a real Postgres test DB (DATABASE_URL)
with 001_init.sql applied; they follow the per-test, loop-local engine /
dependency-override pattern from tests/test_capture.py.

All tests use the Fake clients (agents.clients.FakeEmbeddingsClient /
FakeClaudeClient) — no live API keys required anywhere.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import delete, select, text as sa_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agents import gate
from agents.clients import ClaudeResponse, ClaudeUsage, FakeClaudeClient, FakeEmbeddingsClient
from agents.embeddings import find_duplicate
from agents.sorter import SorterError, TriageResult, classify
from agents.triage import triage_batch
from app.db import _to_async_dsn, get_database_url
from app.models import Note, RawCapture, Reminder, ReviewItem, SkillRun

# ── Sorter validation (pure, no DB / no network) ──────────────────────────


class _StubClaudeClient:
    """Minimal ClaudeClient stub that returns a fixed ClaudeResponse."""

    model = "stub"

    def __init__(self, response: ClaudeResponse):
        self._response = response

    async def complete(self, system: str, user: str) -> ClaudeResponse:
        return self._response


async def test_classify_raises_on_malformed_json():
    bad_response = ClaudeResponse(
        text="not json at all",
        json=None,
        usage=ClaudeUsage(input_tokens=10, output_tokens=5),
        model="stub",
    )
    claude = _StubClaudeClient(bad_response)

    capture = RawCapture(id=uuid.uuid4(), source="ios_quick", body="hello")

    with pytest.raises(SorterError):
        await classify(capture, [], claude=claude)


async def test_classify_raises_on_schema_invalid_json():
    invalid_payload = {
        "type": "not-a-valid-type",
        "tags": [],
        "routing_confidence": 0.5,
    }
    bad_response = ClaudeResponse(
        text="{}",
        json=invalid_payload,
        usage=ClaudeUsage(input_tokens=10, output_tokens=5),
        model="stub",
    )
    claude = _StubClaudeClient(bad_response)

    capture = RawCapture(id=uuid.uuid4(), source="ios_quick", body="hello")

    with pytest.raises(SorterError):
        await classify(capture, [], claude=claude)


async def test_classify_returns_triage_result_for_valid_json():
    capture = RawCapture(id=uuid.uuid4(), source="ios_quick", body="just a fleeting thought")
    claude = FakeClaudeClient()

    result = await classify(capture, [], claude=claude)

    assert isinstance(result, TriageResult)
    assert result.type == "fleeting"
    assert 0.0 <= result.routing_confidence <= 1.0


async def test_classify_steers_to_task_on_todo_body():
    capture = RawCapture(id=uuid.uuid4(), source="ios_quick", body="TODO: buy milk")
    claude = FakeClaudeClient()

    result = await classify(capture, [], claude=claude)

    assert result.type == "task"


async def test_confidence_is_clamped_to_0_1():
    payload = {
        "type": "fleeting",
        "tags": [],
        "domain": None,
        "urgency": None,
        "actionability": None,
        "routing_confidence": 1.5,
        "related_ids": [],
        "duplicate_of": None,
    }
    response = ClaudeResponse(
        text="{}", json=payload, usage=ClaudeUsage(input_tokens=1, output_tokens=1), model="stub"
    )
    claude = _StubClaudeClient(response)
    capture = RawCapture(id=uuid.uuid4(), source="ios_quick", body="x")

    result = await classify(capture, [], claude=claude)

    assert result.routing_confidence == 1.0


# ── Confidence gate (pure, no DB / no network) ────────────────────────────


def _triage(
    type: str = "fleeting",
    confidence: float = 0.85,
    duplicate_of: uuid.UUID | None = None,
    tags: list[str] | None = None,
) -> TriageResult:
    return TriageResult(
        type=type,
        tags=tags or [],
        domain=None,
        urgency=None,
        actionability=None,
        routing_confidence=confidence,
        related_ids=[],
        duplicate_of=duplicate_of,
    )


def test_gate_high_confidence_creates_note_no_review():
    capture_id = uuid.uuid4()
    triage = _triage(confidence=0.9)

    decision = gate.route(capture_id, triage, embedding=[0.0] * 8)

    assert decision.create_note is not None
    assert decision.create_note.confidence == 0.9
    assert gate.NEEDS_REVIEW_TAG not in decision.create_note.tags
    assert decision.create_review_items == []
    assert decision.create_reminder is None


def test_gate_mid_confidence_creates_note_with_needs_review_and_review_item():
    capture_id = uuid.uuid4()
    triage = _triage(confidence=0.6)

    decision = gate.route(capture_id, triage, embedding=[0.0] * 8)

    assert decision.create_note is not None
    assert gate.NEEDS_REVIEW_TAG in decision.create_note.tags
    assert len(decision.create_review_items) == 1
    assert decision.create_review_items[0].reason == "low_confidence"
    assert decision.create_reminder is None


def test_gate_low_confidence_no_note_review_only():
    capture_id = uuid.uuid4()
    triage = _triage(confidence=0.3)

    decision = gate.route(capture_id, triage, embedding=[0.0] * 8)

    assert decision.create_note is None
    assert len(decision.create_review_items) == 1
    assert decision.create_review_items[0].reason == "low_confidence"


def test_gate_duplicate_adds_extra_review_item():
    capture_id = uuid.uuid4()
    dup_id = uuid.uuid4()
    triage = _triage(confidence=0.9, duplicate_of=dup_id)

    decision = gate.route(capture_id, triage, embedding=[0.0] * 8)

    assert decision.create_note is not None
    reasons = [r.reason for r in decision.create_review_items]
    assert reasons == ["duplicate"]


def test_gate_low_confidence_duplicate_has_both_review_items():
    capture_id = uuid.uuid4()
    dup_id = uuid.uuid4()
    triage = _triage(confidence=0.2, duplicate_of=dup_id)

    decision = gate.route(capture_id, triage, embedding=[0.0] * 8)

    assert decision.create_note is None
    reasons = sorted(r.reason for r in decision.create_review_items)
    assert reasons == ["duplicate", "low_confidence"]


def test_gate_task_creates_reminder_regardless_of_confidence():
    capture_id = uuid.uuid4()

    for confidence in (0.95, 0.6, 0.1):
        triage = _triage(type="task", confidence=confidence)
        decision = gate.route(capture_id, triage, embedding=[0.0] * 8)
        assert decision.create_reminder is not None, confidence


# ── Dedup (needs DB) ───────────────────────────────────────────────────────


@pytest.fixture
async def db_session_factory():
    engine = create_async_engine(_to_async_dsn(get_database_url()), future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_find_duplicate_flags_near_identical_embedding(db_session_factory):
    """Insert a note with a known (fake-client) embedding; a capture whose
    fake embedding is identical should be flagged as a duplicate of it."""
    embeddings = FakeEmbeddingsClient()
    text = "a very specific recurring idea about home automation"
    vector = (await embeddings.embed([text]))[0]

    from app.repositories.note import NoteRepository

    async with db_session_factory() as session:
        await session.execute(sa_text("SET ivfflat.probes = 100"))
        note_repo = NoteRepository(session)
        note = await note_repo.create(title="existing note", type="fleeting", embedding=vector)
        await session.commit()

        try:
            neighbors = await note_repo.nearest(vector, k=5)
            dup_id = find_duplicate(vector, neighbors)
            assert dup_id == note.id
        finally:
            await note_repo.delete(note.id)
            await session.commit()


# ── Integration: triage_batch (needs DB) ───────────────────────────────────


@pytest.fixture
async def cleanup_rows(db_session_factory):
    """Tracks ids created during a test and deletes them afterward."""
    tracked: dict[str, list[uuid.UUID]] = {
        "captures": [],
        "notes": [],
        "review_items": [],
        "reminders": [],
        "skill_runs": [],
    }
    yield tracked

    async with db_session_factory() as session:
        if tracked["reminders"]:
            await session.execute(delete(Reminder).where(Reminder.id.in_(tracked["reminders"])))
        if tracked["skill_runs"]:
            await session.execute(delete(SkillRun).where(SkillRun.id.in_(tracked["skill_runs"])))
        if tracked["review_items"]:
            await session.execute(delete(ReviewItem).where(ReviewItem.id.in_(tracked["review_items"])))
        if tracked["notes"]:
            await session.execute(delete(Note).where(Note.id.in_(tracked["notes"])))
        if tracked["captures"]:
            await session.execute(delete(RawCapture).where(RawCapture.id.in_(tracked["captures"])))
        await session.commit()


async def test_triage_batch_processes_pending_captures(db_session_factory, cleanup_rows):
    # Seed 3 pending captures: one "TODO ..." (task), two fleeting.
    bodies = [
        "TODO: call the dentist tomorrow",
        "fleeting thought about gardens",
        "another fleeting note about clouds",
    ]

    async with db_session_factory() as session:
        captures = []
        for body in bodies:
            capture = RawCapture(id=uuid.uuid4(), source="ios_quick", body=body, status="pending")
            session.add(capture)
            captures.append(capture)
        await session.flush()
        await session.commit()
        for c in captures:
            cleanup_rows["captures"].append(c.id)

    claude = FakeClaudeClient()
    embeddings = FakeEmbeddingsClient()

    async with db_session_factory() as session:
        await session.execute(sa_text("SET ivfflat.probes = 100"))
        summaries = await triage_batch(session, limit=10, claude=claude, embeddings=embeddings)

    # Only our 3 seeded captures should be among the pending ones processed
    # (other tests may leave stray pending rows; filter to ours).
    our_ids = {c.id for c in captures}
    our_summaries = [s for s in summaries if s["capture_id"] in our_ids]
    assert len(our_summaries) == 3

    async with db_session_factory() as session:
        # All 3 captures now triaged.
        for capture_id in our_ids:
            row = await session.get(RawCapture, capture_id)
            assert row.status == "triaged"
            assert row.processed_at is not None

        task_summaries = [s for s in our_summaries if s["type"] == "task"]
        fleeting_summaries = [s for s in our_summaries if s["type"] == "fleeting"]
        assert len(task_summaries) == 1
        assert len(fleeting_summaries) == 2

        # Gate distribution: FakeClaudeClient returns confidence 0.9 for
        # tasks and 0.85 for fleeting — both >= DIRECT_WRITE_THRESHOLD
        # (0.80), so every capture gets a note and no review_item (absent
        # duplicates).
        for s in our_summaries:
            assert s["note_id"] is not None
            note = await session.get(Note, s["note_id"])
            assert note is not None
            cleanup_rows["notes"].append(note.id)

        # Task capture also gets a reminder.
        for s in task_summaries:
            assert s["reminder_id"] is not None
            reminder = await session.get(Reminder, s["reminder_id"])
            assert reminder is not None
            assert reminder.status == "scheduled"
            assert reminder.channel == "apns"
            cleanup_rows["reminders"].append(reminder.id)

        for s in fleeting_summaries:
            assert s["reminder_id"] is None

        # One skill_run per capture, skill='sorter'.
        result = await session.execute(
            select(SkillRun).where(SkillRun.note_id.in_([s["note_id"] for s in our_summaries]))
        )
        runs = list(result.scalars().all())
        assert len(runs) == 3
        for run in runs:
            assert run.skill == "sorter"
            cleanup_rows["skill_runs"].append(run.id)

        # No review_items expected for this batch (all high confidence, no
        # dups against an empty/near-empty note table for this fresh text).
        for s in our_summaries:
            for review_id in s["review_item_ids"]:
                cleanup_rows["review_items"].append(review_id)
