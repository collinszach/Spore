"""Repository for raw_capture rows."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
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
