"""Contract tests for POST /capture (Story 1.3).

Runs against a real Postgres test DB (001_init.sql applied) — DATABASE_URL
and SPORE_CAPTURE_TOKEN are read from the environment by app.db / app.config
respectively, matching the convention in tests/test_repositories.py. Each
test cleans up the raw_capture rows it creates.
"""

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import _to_async_dsn, get_database_url, get_session
from app.main import app
from app.models import RawCapture

TOKEN = os.environ.get("SPORE_CAPTURE_TOKEN", "dev-token")


@pytest.fixture
async def db_sessionmaker():
    """Per-test async engine + sessionmaker, built inside the test's event loop.

    The app's module-level engine is bound to the import-time loop; asyncpg
    connections can't cross loops, so tests must use a loop-local engine and
    inject it into the app via dependency_overrides.
    """
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
async def cleanup_capture(db_sessionmaker):
    """Yield a list; deletes raw_capture rows by id after the test runs."""
    ids: list[uuid.UUID] = []
    yield ids
    if ids:
        async with db_sessionmaker() as session:
            await session.execute(delete(RawCapture).where(RawCapture.id.in_(ids)))
            await session.commit()


async def test_capture_happy_path_returns_201(client, cleanup_capture, db_sessionmaker):
    capture_uuid = uuid.uuid4()
    cleanup_capture.append(capture_uuid)

    response = await client.post(
        "/capture",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "capture_uuid": str(capture_uuid),
            "source": "ios_quick",
            "body": "hello world",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["id"] == str(capture_uuid)
    assert payload["data"]["source"] == "ios_quick"
    assert payload["data"]["body"] == "hello world"
    assert payload["data"]["status"] == "pending"

    async with db_sessionmaker() as session:
        row = await session.get(RawCapture, capture_uuid)
        assert row is not None
        assert row.source == "ios_quick"


async def test_capture_missing_token_returns_401(client, cleanup_capture):
    capture_uuid = uuid.uuid4()
    cleanup_capture.append(capture_uuid)

    response = await client.post(
        "/capture",
        json={
            "capture_uuid": str(capture_uuid),
            "source": "ios_quick",
            "body": "no auth header",
        },
    )

    assert response.status_code == 401


async def test_capture_wrong_token_returns_401(client, cleanup_capture):
    capture_uuid = uuid.uuid4()
    cleanup_capture.append(capture_uuid)

    response = await client.post(
        "/capture",
        headers={"Authorization": "Bearer not-the-token"},
        json={
            "capture_uuid": str(capture_uuid),
            "source": "ios_quick",
            "body": "wrong token",
        },
    )

    assert response.status_code == 401


async def test_capture_missing_source_returns_422(client):
    capture_uuid = uuid.uuid4()

    response = await client.post(
        "/capture",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "capture_uuid": str(capture_uuid),
            "body": "missing source field",
        },
    )

    assert response.status_code == 422


async def test_capture_missing_capture_uuid_returns_422(client):
    response = await client.post(
        "/capture",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "source": "ios_quick",
            "body": "missing capture_uuid field",
        },
    )

    assert response.status_code == 422


async def test_capture_retry_is_idempotent(client, cleanup_capture, db_sessionmaker):
    capture_uuid = uuid.uuid4()
    cleanup_capture.append(capture_uuid)
    body = {
        "capture_uuid": str(capture_uuid),
        "source": "ios_quick",
        "body": "idempotent capture",
    }
    headers = {"Authorization": f"Bearer {TOKEN}"}

    first = await client.post("/capture", headers=headers, json=body)
    assert first.status_code == 201

    second = await client.post("/capture", headers=headers, json=body)
    assert second.status_code == 200
    assert second.json()["data"]["id"] == first.json()["data"]["id"]

    async with db_sessionmaker() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(RawCapture).where(RawCapture.id == capture_uuid)
        )
        rows = result.scalars().all()
        assert len(rows) == 1
