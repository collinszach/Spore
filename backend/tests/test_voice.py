"""Contract tests for POST /capture/audio (Story 2.6, ADR-001: local Whisper).

Mirrors tests/test_capture.py: loop-local async engine + get_session
dependency override, real Postgres test DB (001_init.sql applied). The
transcription client is overridden with `FakeTranscriptionClient` — no
network, no live whisper. Audio is written under a tmp media dir via a
`MEDIA_DIR`-pointed settings override; each test cleans up rows and files.
"""

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agents.transcription import FakeTranscriptionClient, get_transcription_client
from app.db import _to_async_dsn, get_database_url, get_session
from app.main import app
from app.models import RawCapture
from app.routers.capture import _get_transcription_client

TOKEN = os.environ.get("SPORE_CAPTURE_TOKEN", "dev-token")


@pytest.fixture
async def db_sessionmaker():
    """Per-test async engine + sessionmaker, built inside the test's event loop."""
    engine = create_async_engine(_to_async_dsn(get_database_url()), future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def client(db_sessionmaker, tmp_path, monkeypatch):
    async def _override_get_session():
        async with db_sessionmaker() as session:
            yield session

    # Point media_dir at a tmp path so test files don't land in the repo.
    monkeypatch.setattr("app.config.settings.media_dir", str(tmp_path))
    monkeypatch.setattr("app.routers.capture.settings.media_dir", str(tmp_path))

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[_get_transcription_client] = lambda: FakeTranscriptionClient()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(_get_transcription_client, None)


@pytest.fixture
async def cleanup_capture(db_sessionmaker):
    """Yield a list; deletes raw_capture rows by id after the test runs."""
    ids: list[uuid.UUID] = []
    yield ids
    if ids:
        async with db_sessionmaker() as session:
            await session.execute(delete(RawCapture).where(RawCapture.id.in_(ids)))
            await session.commit()


def _audio_files(filename: str = "note.m4a", content: bytes = b"fake-audio-bytes"):
    return {"audio": (filename, content, "audio/mp4")}


async def test_voice_capture_happy_path_returns_201(client, cleanup_capture, db_sessionmaker, tmp_path):
    capture_uuid = uuid.uuid4()
    cleanup_capture.append(capture_uuid)

    response = await client.post(
        "/capture/audio",
        headers={"Authorization": f"Bearer {TOKEN}"},
        data={"capture_uuid": str(capture_uuid), "source": "ios_voice"},
        files=_audio_files(),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["ok"] is True
    assert payload["error"] is None
    data = payload["data"]
    assert data["id"] == str(capture_uuid)
    assert data["source"] == "ios_voice"
    assert data["transcribed"] is True
    assert data["body"] == "[transcript of note.m4a]"
    assert data["media_url"]
    assert data["status"] == "pending"

    # File was written under the tmp media dir.
    assert os.path.exists(data["media_url"])
    assert data["media_url"].startswith(str(tmp_path))

    async with db_sessionmaker() as session:
        row = await session.get(RawCapture, capture_uuid)
        assert row is not None
        assert row.transcribed is True
        assert row.body == "[transcript of note.m4a]"


async def test_voice_capture_retry_is_idempotent(client, cleanup_capture, db_sessionmaker):
    capture_uuid = uuid.uuid4()
    cleanup_capture.append(capture_uuid)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    data = {"capture_uuid": str(capture_uuid), "source": "ios_voice"}

    first = await client.post("/capture/audio", headers=headers, data=data, files=_audio_files())
    assert first.status_code == 201

    second = await client.post("/capture/audio", headers=headers, data=data, files=_audio_files())
    assert second.status_code == 200
    assert second.json()["data"]["id"] == first.json()["data"]["id"]

    async with db_sessionmaker() as session:
        from sqlalchemy import select

        result = await session.execute(select(RawCapture).where(RawCapture.id == capture_uuid))
        rows = result.scalars().all()
        assert len(rows) == 1


async def test_voice_capture_missing_token_returns_401(client, cleanup_capture):
    capture_uuid = uuid.uuid4()
    cleanup_capture.append(capture_uuid)

    response = await client.post(
        "/capture/audio",
        data={"capture_uuid": str(capture_uuid), "source": "ios_voice"},
        files=_audio_files(),
    )

    assert response.status_code == 401


async def test_voice_capture_wrong_token_returns_401(client, cleanup_capture):
    capture_uuid = uuid.uuid4()
    cleanup_capture.append(capture_uuid)

    response = await client.post(
        "/capture/audio",
        headers={"Authorization": "Bearer not-the-token"},
        data={"capture_uuid": str(capture_uuid), "source": "ios_voice"},
        files=_audio_files(),
    )

    assert response.status_code == 401


async def test_voice_capture_missing_audio_returns_422(client):
    capture_uuid = uuid.uuid4()

    response = await client.post(
        "/capture/audio",
        headers={"Authorization": f"Bearer {TOKEN}"},
        data={"capture_uuid": str(capture_uuid), "source": "ios_voice"},
    )

    assert response.status_code == 422


async def test_voice_capture_missing_capture_uuid_returns_422(client):
    response = await client.post(
        "/capture/audio",
        headers={"Authorization": f"Bearer {TOKEN}"},
        data={"source": "ios_voice"},
        files=_audio_files(),
    )

    assert response.status_code == 422


def test_get_transcription_client_factory_default_is_fake():
    assert isinstance(get_transcription_client(), FakeTranscriptionClient)
