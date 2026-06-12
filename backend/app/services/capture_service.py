"""Service layer for capture ingestion (Story 1.3).

Maps validated `CaptureIn` input to a CaptureRepository call and commits the
transaction. Routers should call this — no direct DB access in routers.
"""

from __future__ import annotations

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
