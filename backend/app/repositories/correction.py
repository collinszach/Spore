"""Repository for correction rows (FR14 — training signal)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Correction


class CorrectionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        review_item_id: uuid.UUID | None,
        original_json: dict | None,
        corrected_json: dict | None,
    ) -> Correction:
        correction = Correction(
            review_item_id=review_item_id,
            original_json=original_json,
            corrected_json=corrected_json,
        )
        self.session.add(correction)
        await self.session.flush()
        return correction

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Correction))
        return int(result.scalar_one())

    async def list_recent(self, limit: int = 10) -> list[Correction]:
        stmt = select(Correction).order_by(Correction.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
