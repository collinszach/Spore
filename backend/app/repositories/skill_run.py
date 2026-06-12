"""Repository for skill_run rows (cost ledger)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SkillRun


class SkillRunRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **fields) -> SkillRun:
        run = SkillRun(**fields)
        self.session.add(run)
        await self.session.flush()
        return run

    async def get(self, skill_run_id: uuid.UUID) -> SkillRun | None:
        return await self.session.get(SkillRun, skill_run_id)

    async def list(self, skill: str | None = None, limit: int = 100) -> list[SkillRun]:
        stmt = select(SkillRun).order_by(SkillRun.created_at.desc()).limit(limit)
        if skill is not None:
            stmt = stmt.where(SkillRun.skill == skill)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, skill_run_id: uuid.UUID, **fields) -> SkillRun | None:
        run = await self.get(skill_run_id)
        if run is None:
            return None
        for key, value in fields.items():
            setattr(run, key, value)
        await self.session.flush()
        return run

    async def delete(self, skill_run_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            delete(SkillRun).where(SkillRun.id == skill_run_id)
        )
        return result.rowcount > 0
