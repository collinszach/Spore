"""Repository unit tests against a real Postgres test DB (001_init.sql applied).

Each test opens its own session/transaction and cleans up the rows it
creates (delete or rollback) so the DB is left as it was found.

DATABASE_URL is read from the environment by app.db; the PM points it at a
test database with the schema already applied.
"""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import _to_async_dsn
from app.repositories.capture import CaptureRepository
from app.repositories.note import NoteRepository
from app.repositories.skill_run import SkillRunRepository


@pytest.fixture
async def session():
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(_to_async_dsn(database_url), future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        # Scan all ivfflat lists so kNN has full recall on the tiny test table
        # (lists=100 on a few rows otherwise probes one mostly-empty list).
        await session.execute(text("SET ivfflat.probes = 100"))
        yield session
        await session.rollback()
    await engine.dispose()


def _vector(dim: int, hot_index: int) -> list[float]:
    """A 1024-dim vector that is all zeros except a 1.0 at `hot_index`."""
    vec = [0.0] * dim
    vec[hot_index] = 1.0
    return vec


async def test_capture_create_get_update_delete(session):
    repo = CaptureRepository(session)

    capture = await repo.create(source="ios_quick", body="hello world")
    await session.commit()

    fetched = await repo.get(capture.id)
    assert fetched is not None
    assert fetched.source == "ios_quick"
    assert fetched.body == "hello world"
    assert fetched.status == "pending"

    updated = await repo.update(capture.id, status="triaged")
    await session.commit()
    assert updated is not None
    assert updated.status == "triaged"

    refetched = await repo.get(capture.id)
    assert refetched is not None
    assert refetched.status == "triaged"

    deleted = await repo.delete(capture.id)
    await session.commit()
    assert deleted is True

    assert await repo.get(capture.id) is None


async def test_note_knn_returns_ordered_neighbors(session):
    note_repo = NoteRepository(session)
    dim = 1024

    # Three notes with distinct one-hot embeddings.
    note_a = await note_repo.create(
        title="note a", type="fleeting", embedding=_vector(dim, 0)
    )
    note_b = await note_repo.create(
        title="note b", type="fleeting", embedding=_vector(dim, 1)
    )
    note_c = await note_repo.create(
        title="note c", type="fleeting", embedding=_vector(dim, 2)
    )
    await session.commit()

    try:
        # Query vector is closest to note_a (identical), then note_b and
        # note_c are equidistant from it but we only need note_a first.
        query_vec = _vector(dim, 0)
        results = await note_repo.nearest(query_vec, k=3)

        result_ids = [n.id for n in results]
        assert result_ids[0] == note_a.id
        assert set(result_ids) == {note_a.id, note_b.id, note_c.id}

        # A query closer to note_b should rank note_b first.
        query_vec_b = _vector(dim, 1)
        results_b = await note_repo.nearest(query_vec_b, k=3)
        assert results_b[0].id == note_b.id
    finally:
        for note in (note_a, note_b, note_c):
            await note_repo.delete(note.id)
        await session.commit()


async def test_skill_run_create_and_note_with_embedding(session):
    note_repo = NoteRepository(session)
    skill_repo = SkillRunRepository(session)
    dim = 1024

    note = await note_repo.create(
        title="embedded note",
        type="fleeting",
        embedding=_vector(dim, 5),
    )
    await session.commit()
    assert note.id is not None
    assert note.embedding is not None

    run = await skill_repo.create(
        skill="sorter",
        note_id=note.id,
        status="ok",
        model="claude-test",
        tokens_in=100,
        tokens_out=50,
        cost_usd="0.00123",
    )
    await session.commit()
    assert run.id is not None

    fetched_run = await skill_repo.get(run.id)
    assert fetched_run is not None
    assert fetched_run.skill == "sorter"
    assert fetched_run.note_id == note.id

    # Cleanup
    await skill_repo.delete(run.id)
    await note_repo.delete(note.id)
    await session.commit()
