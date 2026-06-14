"""Contract tests for POST /devices (Story 1.4 device-auth).

Runs against a real Postgres test DB (001_init.sql applied) — same
loop-local engine + get_session override pattern as test_capture.py.
"""

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import _to_async_dsn, get_database_url, get_session
from app.main import app
from app.models import Device

TOKEN = os.environ.get("SPORE_CAPTURE_TOKEN", "dev-token")


@pytest.fixture
async def db_sessionmaker():
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
async def cleanup_device(db_sessionmaker):
    """Yield a list; deletes device rows by apns_token after the test runs."""
    tokens: list[str] = []
    yield tokens
    if tokens:
        async with db_sessionmaker() as session:
            await session.execute(delete(Device).where(Device.apns_token.in_(tokens)))
            await session.commit()


async def test_register_device_returns_201(client, cleanup_device, db_sessionmaker):
    apns_token = f"test-token-{uuid.uuid4()}"
    cleanup_device.append(apns_token)

    response = await client.post(
        "/devices",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"apns_token": apns_token, "platform": "ios"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["apns_token"] == apns_token
    assert payload["data"]["platform"] == "ios"

    async with db_sessionmaker() as session:
        from sqlalchemy import select

        result = await session.execute(select(Device).where(Device.apns_token == apns_token))
        row = result.scalar_one_or_none()
        assert row is not None


async def test_register_device_is_idempotent(client, cleanup_device, db_sessionmaker):
    apns_token = f"test-token-{uuid.uuid4()}"
    cleanup_device.append(apns_token)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    body = {"apns_token": apns_token, "platform": "ios"}

    first = await client.post("/devices", headers=headers, json=body)
    assert first.status_code == 201
    first_id = first.json()["data"]["id"]

    second = await client.post("/devices", headers=headers, json=body)
    assert second.status_code == 200
    assert second.json()["data"]["id"] == first_id

    async with db_sessionmaker() as session:
        from sqlalchemy import select

        result = await session.execute(select(Device).where(Device.apns_token == apns_token))
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].last_seen is not None


async def test_register_device_missing_token_returns_401(client, cleanup_device):
    apns_token = f"test-token-{uuid.uuid4()}"
    cleanup_device.append(apns_token)

    response = await client.post(
        "/devices",
        json={"apns_token": apns_token, "platform": "ios"},
    )

    assert response.status_code == 401


async def test_register_device_missing_apns_token_returns_422(client):
    response = await client.post(
        "/devices",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"platform": "ios"},
    )

    assert response.status_code == 422
