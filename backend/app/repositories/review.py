"""Repository for review_item rows."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReviewItem


class ReviewRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **fields) -> ReviewItem:
        item = ReviewItem(**fields)
        self.session.add(item)
        await self.session.flush()
        return item

    async def get(self, review_item_id: uuid.UUID) -> ReviewItem | None:
        return await self.session.get(ReviewItem, review_item_id)

    async def list(self, status: str | None = None, limit: int = 100) -> list[ReviewItem]:
        stmt = select(ReviewItem).order_by(ReviewItem.created_at.desc()).limit(limit)
        if status is not None:
            stmt = stmt.where(ReviewItem.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, review_item_id: uuid.UUID, **fields) -> ReviewItem | None:
        item = await self.get(review_item_id)
        if item is None:
            return None
        for key, value in fields.items():
            setattr(item, key, value)
        await self.session.flush()
        return item

    async def delete(self, review_item_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            delete(ReviewItem).where(ReviewItem.id == review_item_id)
        )
        return result.rowcount > 0
