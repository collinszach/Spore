"""Repository for correction rows (FR14 — training signal)."""

from __future__ import annotations

import uuid

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
