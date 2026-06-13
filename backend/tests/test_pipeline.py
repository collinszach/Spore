"""Contract tests for Epic 7 — idea pipeline & state machine (Stories 7.1/7.3/7.4).

DB-backed tests run against a real Postgres test DB (001_init.sql applied),
following the loop-local engine + get_session override pattern from
tests/test_capture.py. The transition-map test at the bottom has no DB
dependency and can run anywhere.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import _to_async_dsn, get_database_url, get_session
from app.main import app
from app.models import IdeaEvent, Note, NoteLink
from app.pipeline import ALLOWED_TRANSITIONS, can_transition, next_forward_state

TOKEN = os.environ.get("SPORE_CAPTURE_TOKEN", "dev-token")


@pytest.fixture
async def db_sessionmaker():
    """Per-test async engine + sessionmaker, built inside the test's event loop."""
    engine = create_async_engine(_to_async_dsn(get_database_url()), future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def client(db_sessionmaker):
    async def _override_get_session():
        async with db_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
async def cleanup(db_sessionmaker):
    """Tracks ids per-table; deletes them (in FK-safe order) after the test."""
    state = {
        "idea_event": [],
        "note_link": [],
        "note": [],
    }
    yield state
    async with db_sessionmaker() as session:
        if state["idea_event"]:
            await session.execute(delete(IdeaEvent).where(IdeaEvent.id.in_(state["idea_event"])))
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


# ── 7.1 — state machine ────────────────────────────────────────────────


async def test_move_valid_transition_persists_and_logs_event(client, db_sessionmaker, cleanup):
    note = await _make_note(db_sessionmaker, cleanup, title="Seedling note", idea_state="seedling")

    response = await client.post(
        f"/pipeline/{note.id}/move",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"to_state": "sapling"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["idea_state"] == "sapling"

    async with db_sessionmaker() as session:
        refreshed = await session.get(Note, note.id)
        assert refreshed.idea_state == "sapling"

        result = await session.execute(
            delete(IdeaEvent).where(IdeaEvent.note_id == note.id).returning(IdeaEvent.id, IdeaEvent.from_state, IdeaEvent.to_state)
        )
        rows = result.all()
        await session.commit()

    assert len(rows) == 1
    assert rows[0].from_state == "seedling"
    assert rows[0].to_state == "sapling"
    cleanup["idea_event"].extend(r.id for r in rows)


async def test_move_invalid_transition_returns_409_with_allowed_list(client, db_sessionmaker, cleanup):
    note = await _make_note(db_sessionmaker, cleanup, title="Seedling note", idea_state="seedling")

    response = await client.post(
        f"/pipeline/{note.id}/move",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"to_state": "project"},
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["ok"] is False
    assert "sapling" in payload["error"]["allowed_transitions"]
    assert "project" not in payload["error"]["allowed_transitions"]

    async with db_sessionmaker() as session:
        refreshed = await session.get(Note, note.id)
        assert refreshed.idea_state == "seedling"


async def test_move_unknown_note_returns_404(client):
    response = await client.post(
        f"/pipeline/{uuid.uuid4()}/move",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"to_state": "sapling"},
    )
    assert response.status_code == 404
    assert response.json()["ok"] is False


async def test_get_pipeline_groups_notes_by_state_with_counts(client, db_sessionmaker, cleanup):
    seedling = await _make_note(db_sessionmaker, cleanup, title="A seedling", idea_state="seedling")
    sapling = await _make_note(db_sessionmaker, cleanup, title="A sapling", idea_state="sapling")

    response = await client.get("/pipeline", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True

    states = payload["data"]["states"]
    counts = payload["data"]["counts"]

    seedling_ids = {n["id"] for n in states["seedling"]}
    sapling_ids = {n["id"] for n in states["sapling"]}
    assert str(seedling.id) in seedling_ids
    assert str(sapling.id) in sapling_ids
    assert counts["seedling"] >= 1
    assert counts["sapling"] >= 1


# ── 7.3 — promotion suggestions ───────────────────────────────────────


async def test_promotion_suggestion_appears_for_note_with_enough_incoming_links(
    client, db_sessionmaker, cleanup
):
    target = await _make_note(db_sessionmaker, cleanup, title="Popular idea", idea_state="seedling")
    referrers = [
        await _make_note(db_sessionmaker, cleanup, title=f"Referrer {i}", idea_state="sprout")
        for i in range(3)
    ]

    async with db_sessionmaker() as session:
        for ref in referrers:
            link = NoteLink(src_id=ref.id, dst_id=target.id, kind="related")
            session.add(link)
            cleanup["note_link"].append((ref.id, target.id, "related"))
        await session.commit()

    response = await client.get("/pipeline/suggestions", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    payload = response.json()
    promotions = {p["note_id"]: p for p in payload["data"]["promotions"]}
    assert str(target.id) in promotions
    promo = promotions[str(target.id)]
    assert promo["current_state"] == "seedling"
    assert promo["suggested_state"] == "sapling"
    assert promo["ref_count"] >= 3


async def test_note_with_fewer_than_threshold_links_not_suggested(client, db_sessionmaker, cleanup):
    target = await _make_note(db_sessionmaker, cleanup, title="Unpopular idea", idea_state="seedling")
    referrer = await _make_note(db_sessionmaker, cleanup, title="Lone referrer", idea_state="sprout")

    async with db_sessionmaker() as session:
        link = NoteLink(src_id=referrer.id, dst_id=target.id, kind="related")
        session.add(link)
        cleanup["note_link"].append((referrer.id, target.id, "related"))
        await session.commit()

    response = await client.get("/pipeline/suggestions", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    payload = response.json()
    promotion_ids = {p["note_id"] for p in payload["data"]["promotions"]}
    assert str(target.id) not in promotion_ids


# ── 7.4 — stale-idea detection ────────────────────────────────────────


async def test_stale_seedling_appears_in_suggestions(client, db_sessionmaker, cleanup):
    old_updated = datetime.now(timezone.utc) - timedelta(days=20)
    stale_note = await _make_note(
        db_sessionmaker, cleanup, title="Old seedling", idea_state="seedling", updated_at=old_updated
    )
    fresh_note = await _make_note(
        db_sessionmaker, cleanup, title="Fresh seedling", idea_state="seedling"
    )

    response = await client.get("/pipeline/suggestions", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    payload = response.json()
    stale_ids = {s["note_id"] for s in payload["data"]["stale"]}
    assert str(stale_note.id) in stale_ids
    assert str(fresh_note.id) not in stale_ids

    stale_entry = next(s for s in payload["data"]["stale"] if s["note_id"] == str(stale_note.id))
    assert stale_entry["suggested_actions"] == ["promote", "merge", "archive"]


async def test_stale_sweep_endpoint_returns_stale_notes_idempotently(client, db_sessionmaker, cleanup):
    old_updated = datetime.now(timezone.utc) - timedelta(days=30)
    stale_note = await _make_note(
        db_sessionmaker, cleanup, title="Very old seedling", idea_state="seedling", updated_at=old_updated
    )

    first = await client.post("/internal/stale-sweep", headers={"Authorization": f"Bearer {TOKEN}"})
    second = await client.post("/internal/stale-sweep", headers={"Authorization": f"Bearer {TOKEN}"})

    assert first.status_code == 200
    assert second.status_code == 200

    first_ids = [s["note_id"] for s in first.json()["data"]["stale"]]
    second_ids = [s["note_id"] for s in second.json()["data"]["stale"]]

    assert str(stale_note.id) in first_ids
    assert str(stale_note.id) in second_ids
    # Idempotent: no duplicate entries pile up across repeated sweeps.
    assert first_ids.count(str(stale_note.id)) == 1
    assert second_ids.count(str(stale_note.id)) == 1


# ── auth ─────────────────────────────────────────────────────────────


async def test_get_pipeline_missing_token_returns_401(client):
    response = await client.get("/pipeline")
    assert response.status_code == 401


async def test_get_suggestions_missing_token_returns_401(client):
    response = await client.get("/pipeline/suggestions")
    assert response.status_code == 401


async def test_move_missing_token_returns_401(client):
    response = await client.post(f"/pipeline/{uuid.uuid4()}/move", json={"to_state": "sapling"})
    assert response.status_code == 401


async def test_stale_sweep_missing_token_returns_401(client):
    response = await client.post("/internal/stale-sweep")
    assert response.status_code == 401


# ── pure unit tests — transition-validity map (no DB) ──────────────────


def test_seedling_to_sapling_is_valid():
    assert can_transition("seedling", "sapling") is True


def test_seedling_to_project_is_invalid():
    assert can_transition("seedling", "project") is False


def test_archived_can_only_revive_to_seedling():
    assert ALLOWED_TRANSITIONS["archived"] == {"seedling"}


def test_shipped_can_only_archive():
    assert ALLOWED_TRANSITIONS["shipped"] == {"archived"}


def test_next_forward_state_for_terminal_states_is_none():
    assert next_forward_state("shipped") is None
    assert next_forward_state("archived") is None


def test_next_forward_state_chain():
    assert next_forward_state("seedling") == "sapling"
    assert next_forward_state("sapling") == "sprout"
    assert next_forward_state("sprout") == "project"
    assert next_forward_state("project") == "shipped"
