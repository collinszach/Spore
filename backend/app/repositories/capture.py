"""Repository for raw_capture rows."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RawCapture


class CaptureRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **fields) -> RawCapture:
        capture = RawCapture(**fields)
        self.session.add(capture)
        await self.session.flush()
        return capture

    async def create_idempotent(
        self,
        capture_uuid: uuid.UUID,
        source: str,
        body: str | None = None,
        media_url: str | None = None,
        lang: str | None = None,
        device_id: uuid.UUID | None = None,
    ) -> tuple[RawCapture, bool]:
        """Insert a raw_capture using `capture_uuid` as the PK, idempotently.

        Uses INSERT ... ON CONFLICT (id) DO NOTHING so a retry with the same
        `capture_uuid` never creates a duplicate row. Returns (row, created)
        where `created` is True only on the first insert.
        """
        stmt = (
            pg_insert(RawCapture)
            .values(
                id=capture_uuid,
                source=source,
                body=body,
                media_url=media_url,
                lang=lang,
                device_id=device_id,
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(RawCapture.id)
        )
        result = await self.session.execute(stmt)
        created = result.first() is not None
        await self.session.flush()

        capture = await self.get(capture_uuid)
        assert capture is not None
        return capture, created

    async def get(self, capture_id: uuid.UUID) -> RawCapture | None:
        return await self.session.get(RawCapture, capture_id)

    async def list(self, status: str | None = None, limit: int = 100) -> list[RawCapture]:
        stmt = select(RawCapture).order_by(RawCapture.created_at.desc()).limit(limit)
        if status is not None:
            stmt = stmt.where(RawCapture.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, capture_id: uuid.UUID, **fields) -> RawCapture | None:
        capture = await self.get(capture_id)
        if capture is None:
            return None
        for key, value in fields.items():
            setattr(capture, key, value)
        await self.session.flush()
        return capture

    async def delete(self, capture_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            delete(RawCapture).where(RawCapture.id == capture_id)
        )
        return result.rowcount > 0
