"""Repository for reminder rows."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reminder


class ReminderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **fields) -> Reminder:
        reminder = Reminder(**fields)
        self.session.add(reminder)
        await self.session.flush()
        return reminder

    async def get(self, reminder_id: uuid.UUID) -> Reminder | None:
        return await self.session.get(Reminder, reminder_id)

    async def list(self, status: str | None = None, limit: int = 100) -> list[Reminder]:
        stmt = select(Reminder).order_by(Reminder.fire_at.asc()).limit(limit)
        if status is not None:
            stmt = stmt.where(Reminder.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, reminder_id: uuid.UUID, **fields) -> Reminder | None:
        reminder = await self.get(reminder_id)
        if reminder is None:
            return None
        for key, value in fields.items():
            setattr(reminder, key, value)
        await self.session.flush()
        return reminder

    async def delete(self, reminder_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            delete(Reminder).where(Reminder.id == reminder_id)
        )
        return result.rowcount > 0
