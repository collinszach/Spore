"""Contract tests for GET /review and POST /review/{id}/{action} (Story 4.2/4.4).

Runs against a real Postgres test DB (001_init.sql applied) — DATABASE_URL
and SPORE_CAPTURE_TOKEN are read from the environment, matching the
convention in tests/test_capture.py. Embeddings use FakeEmbeddingsClient
(no network/API key needed). Each test cleans up the rows it creates.
"""

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agents.clients import FakeEmbeddingsClient
from app.db import _to_async_dsn, get_database_url, get_session
from app.main import app
from app.models import Correction, IdeaEvent, Note, RawCapture, ReviewItem
from app.repositories.capture import CaptureRepository
from app.repositories.note import NoteRepository
from app.repositories.review import ReviewRepository
from app.routers.review import _get_embeddings_client, _get_vault_writer
from app.vault import NoteDoc, VaultWriter

TOKEN = os.environ.get("SPORE_CAPTURE_TOKEN", "dev-token")


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
async def db_sessionmaker():
    """Per-test async engine + sessionmaker, built inside the test's event loop."""
    engine = create_async_engine(_to_async_dsn(get_database_url()), future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


class SpyVaultWriter:
    """Records write_note calls; never touches the filesystem."""

    def __init__(self):
        self.calls: list[NoteDoc] = []

    async def write_note(self, doc: NoteDoc) -> str:
        self.calls.append(doc)
        return f"00_Inbox/{doc.note_id}.md"


@pytest.fixture
async def vault_spy():
    return SpyVaultWriter()


@pytest.fixture
async def client(db_sessionmaker, vault_spy):
    async def _override_get_session():
        async with db_sessionmaker() as session:
            yield session

    def _override_embeddings():
        return FakeEmbeddingsClient()

    def _override_vault_writer() -> VaultWriter:
        return vault_spy

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[_get_embeddings_client] = _override_embeddings
    app.dependency_overrides[_get_vault_writer] = _override_vault_writer
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(_get_embeddings_client, None)
    app.dependency_overrides.pop(_get_vault_writer, None)


@pytest.fixture
async def cleanup(db_sessionmaker):
    """Tracks ids per-table; deletes them (in FK-safe order) after the test."""
    state = {
        "review_item": [],
        "correction": [],
        "note": [],
        "idea_event": [],
        "raw_capture": [],
    }
    yield state
    async with db_sessionmaker() as session:
        if state["correction"]:
            await session.execute(delete(Correction).where(Correction.id.in_(state["correction"])))
        if state["idea_event"]:
            await session.execute(delete(IdeaEvent).where(IdeaEvent.id.in_(state["idea_event"])))
        if state["review_item"]:
            await session.execute(delete(ReviewItem).where(ReviewItem.id.in_(state["review_item"])))
        if state["note"]:
            await session.execute(delete(Note).where(Note.id.in_(state["note"])))
        if state["raw_capture"]:
            await session.execute(delete(RawCapture).where(RawCapture.id.in_(state["raw_capture"])))
        await session.commit()


# ── Seed helpers ─────────────────────────────────────────────────────────


async def _seed_floor_case(db_sessionmaker, cleanup, body="floor case capture body\nmore text"):
    """Below-floor case: capture + open review_item, no note yet."""
    async with db_sessionmaker() as session:
        capture_repo = CaptureRepository(session)
        review_repo = ReviewRepository(session)

        capture = await capture_repo.create(source="ios_quick", body=body)
        item = await review_repo.create(
            capture_id=capture.id,
            reason="low_confidence",
            status="open",
            suggested_type="fleeting",
            suggested_path=None,
            confidence=0.3,
        )
        await session.commit()

        cleanup["raw_capture"].append(capture.id)
        cleanup["review_item"].append(item.id)
        return capture, item


async def _seed_needs_review_case(db_sessionmaker, cleanup, body="needs review capture body\nmore text"):
    """0.50-0.80 case: capture + note (tagged needs-review) + open review_item."""
    async with db_sessionmaker() as session:
        capture_repo = CaptureRepository(session)
        review_repo = ReviewRepository(session)
        note_repo = NoteRepository(session)

        capture = await capture_repo.create(source="ios_quick", body=body)
        embedding = (await FakeEmbeddingsClient().embed([body]))[0]
        note = await note_repo.create(
            title="needs review capture body",
            type="fleeting",
            tags=["fleeting", "needs-review"],
            idea_state="seedling",
            confidence=0.65,
            embedding=embedding,
            source_capture_id=capture.id,
        )
        item = await review_repo.create(
            capture_id=capture.id,
            reason="low_confidence",
            status="open",
            suggested_type="fleeting",
            suggested_path=None,
            confidence=0.65,
        )
        await session.commit()

        cleanup["raw_capture"].append(capture.id)
        cleanup["note"].append(note.id)
        cleanup["review_item"].append(item.id)
        return capture, note, item


async def _seed_target_note(db_sessionmaker, cleanup, body="existing target note body"):
    async with db_sessionmaker() as session:
        capture_repo = CaptureRepository(session)
        note_repo = NoteRepository(session)

        capture = await capture_repo.create(source="ios_quick", body=body)
        embedding = (await FakeEmbeddingsClient().embed([body]))[0]
        note = await note_repo.create(
            title="existing target note",
            type="fleeting",
            tags=["fleeting"],
            idea_state="seedling",
            confidence=0.9,
            embedding=embedding,
            source_capture_id=capture.id,
        )
        await session.commit()

        cleanup["raw_capture"].append(capture.id)
        cleanup["note"].append(note.id)
        return note


# ── GET /review ──────────────────────────────────────────────────────────


async def test_list_open_review_items(client, db_sessionmaker, cleanup):
    capture, item = await _seed_floor_case(db_sessionmaker, cleanup)

    response = await client.get(
        "/review", params={"status": "open"}, headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    ids = [row["id"] for row in payload["data"]]
    assert str(item.id) in ids


async def test_list_review_missing_token_returns_401(client):
    response = await client.get("/review", params={"status": "open"})
    assert response.status_code == 401


# ── approve ──────────────────────────────────────────────────────────────


async def test_approve_floor_case_creates_note_and_logs_idea_event(
    client, db_sessionmaker, cleanup, vault_spy
):
    capture, item = await _seed_floor_case(db_sessionmaker, cleanup)

    response = await client.post(
        f"/review/{item.id}/approve", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["status"] == "approved"

    async with db_sessionmaker() as session:
        note_repo = NoteRepository(session)
        note = await note_repo.get_by_source_capture(capture.id)
        assert note is not None
        assert note.embedding is not None
        assert note.type == "fleeting"
        assert note.title == "floor case capture body"
        assert note.vault_path == f"00_Inbox/{note.id}.md"
        cleanup["note"].append(note.id)

        from sqlalchemy import select

        events = (
            await session.execute(select(IdeaEvent).where(IdeaEvent.note_id == note.id))
        ).scalars().all()
        assert len(events) == 1
        assert events[0].to_state == "seedling"
        assert events[0].reason == "manual"
        cleanup["idea_event"].append(events[0].id)

    assert len(vault_spy.calls) == 1
    assert vault_spy.calls[0].note_id == str(note.id)


async def test_approve_needs_review_case_removes_tag(client, db_sessionmaker, cleanup, vault_spy):
    capture, note, item = await _seed_needs_review_case(db_sessionmaker, cleanup)

    response = await client.post(
        f"/review/{item.id}/approve", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "approved"

    async with db_sessionmaker() as session:
        note_repo = NoteRepository(session)
        refetched = await note_repo.get(note.id)
        assert refetched is not None
        assert "needs-review" not in (refetched.tags or [])
        assert "fleeting" in (refetched.tags or [])

        from sqlalchemy import select

        events = (
            await session.execute(select(IdeaEvent).where(IdeaEvent.note_id == note.id))
        ).scalars().all()
        for e in events:
            cleanup["idea_event"].append(e.id)

    assert len(vault_spy.calls) == 1


# ── redirect ─────────────────────────────────────────────────────────────


async def test_redirect_writes_correction_and_updates_note(client, db_sessionmaker, cleanup, vault_spy):
    capture, item = await _seed_floor_case(db_sessionmaker, cleanup, body="redirect me\nbody")

    response = await client.post(
        f"/review/{item.id}/redirect",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"type": "reference", "tags": ["reference", "research"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["status"] == "redirected"

    async with db_sessionmaker() as session:
        note_repo = NoteRepository(session)
        note = await note_repo.get_by_source_capture(capture.id)
        assert note is not None
        assert note.type == "reference"
        assert note.tags == ["reference", "research"]
        assert note.embedding is not None
        cleanup["note"].append(note.id)

        from sqlalchemy import select

        corrections = (
            await session.execute(select(Correction).where(Correction.review_item_id == item.id))
        ).scalars().all()
        assert len(corrections) == 1
        c = corrections[0]
        assert c.original_json["suggested_type"] == "fleeting"
        assert c.corrected_json["type"] == "reference"
        assert c.corrected_json["tags"] == ["reference", "research"]
        cleanup["correction"].append(c.id)

    assert len(vault_spy.calls) == 1


# ── merge ────────────────────────────────────────────────────────────────


async def test_merge_removes_needs_review_note_and_records_linkage(
    client, db_sessionmaker, cleanup, vault_spy
):
    capture, note, item = await _seed_needs_review_case(db_sessionmaker, cleanup, body="dup capture\nbody")
    target = await _seed_target_note(db_sessionmaker, cleanup)

    response = await client.post(
        f"/review/{item.id}/merge",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"target_note_id": str(target.id)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["status"] == "merged"

    async with db_sessionmaker() as session:
        note_repo = NoteRepository(session)
        assert await note_repo.get(note.id) is None

        from sqlalchemy import select

        corrections = (
            await session.execute(select(Correction).where(Correction.review_item_id == item.id))
        ).scalars().all()
        assert len(corrections) == 1
        assert corrections[0].corrected_json["merged_into_note_id"] == str(target.id)
        cleanup["correction"].append(corrections[0].id)

    # Remove the (already-deleted) note id from cleanup to avoid double-delete noise.
    cleanup["note"] = [nid for nid in cleanup["note"] if nid != note.id]

    assert len(vault_spy.calls) == 0


async def test_merge_floor_case_marks_merged_without_note(client, db_sessionmaker, cleanup):
    capture, item = await _seed_floor_case(db_sessionmaker, cleanup, body="floor dup\nbody")
    target = await _seed_target_note(db_sessionmaker, cleanup)

    response = await client.post(
        f"/review/{item.id}/merge",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"target_note_id": str(target.id)},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "merged"


# ── discard ──────────────────────────────────────────────────────────────


async def test_discard_deletes_needs_review_note(client, db_sessionmaker, cleanup):
    capture, note, item = await _seed_needs_review_case(db_sessionmaker, cleanup, body="discard me\nbody")

    response = await client.post(
        f"/review/{item.id}/discard", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "discarded"

    async with db_sessionmaker() as session:
        note_repo = NoteRepository(session)
        assert await note_repo.get(note.id) is None

    cleanup["note"] = [nid for nid in cleanup["note"] if nid != note.id]


async def test_discard_floor_case_no_note(client, db_sessionmaker, cleanup):
    capture, item = await _seed_floor_case(db_sessionmaker, cleanup, body="discard floor\nbody")

    response = await client.post(
        f"/review/{item.id}/discard", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "discarded"


# ── Error cases ──────────────────────────────────────────────────────────


async def test_action_on_resolved_item_returns_409(client, db_sessionmaker, cleanup):
    capture, item = await _seed_floor_case(db_sessionmaker, cleanup, body="resolved already\nbody")

    first = await client.post(
        f"/review/{item.id}/discard", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert first.status_code == 200

    second = await client.post(
        f"/review/{item.id}/discard", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert second.status_code == 409
    assert second.json()["ok"] is False


async def test_action_on_unknown_id_returns_404(client):
    response = await client.post(
        f"/review/{uuid.uuid4()}/approve", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 404


async def test_action_with_bad_action_returns_400(client, db_sessionmaker, cleanup):
    capture, item = await _seed_floor_case(db_sessionmaker, cleanup, body="bad action\nbody")

    response = await client.post(
        f"/review/{item.id}/frobnicate", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 400


async def test_action_missing_token_returns_401(client, db_sessionmaker, cleanup):
    capture, item = await _seed_floor_case(db_sessionmaker, cleanup, body="no token\nbody")

    response = await client.post(f"/review/{item.id}/approve")
    assert response.status_code == 401
