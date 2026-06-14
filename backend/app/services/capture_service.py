"""Service layer for capture ingestion (Story 1.3).

Maps validated `CaptureIn` input to a CaptureRepository call and commits the
transaction. Routers should call this — no direct DB access in routers.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RawCapture
from app.repositories.capture import CaptureRepository
from app.schemas import CaptureIn


async def ingest_capture(session: AsyncSession, payload: CaptureIn) -> tuple[RawCapture, bool]:
    """Create (or fetch, if a retry) a raw_capture row for `payload`.

    Returns (capture, created) — `created` is True only the first time
    `payload.capture_uuid` is seen.
    """
    repo = CaptureRepository(session)
    capture, created = await repo.create_idempotent(
        capture_uuid=payload.capture_uuid,
        source=payload.source,
        body=payload.body,
        media_url=payload.media_url,
        lang=payload.lang,
        device_id=payload.device_id,
    )
    await session.commit()
    return capture, created


async def ingest_voice_capture(
    session: AsyncSession,
    capture_uuid: uuid.UUID,
    source: str,
    transcript: str,
    media_url: str,
    lang: str | None = None,
) -> tuple[RawCapture, bool]:
    """Create (or fetch, if a retry) a raw_capture row for a transcribed voice capture.

    `transcript` becomes `body`; `transcribed=True` and `media_url` points at
    the saved audio file. Returns (capture, created) — `created` is True only
    the first time `capture_uuid` is seen (Story 2.6).
    """
    repo = CaptureRepository(session)
    capture, created = await repo.create_idempotent(
        capture_uuid=capture_uuid,
        source=source,
        body=transcript,
        media_url=media_url,
        lang=lang,
        transcribed=True,
    )
    await session.commit()
    return capture, created
