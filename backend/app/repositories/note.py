"""Repository for note rows, including pgvector kNN lookups."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note


class NoteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **fields) -> Note:
        note = Note(**fields)
        self.session.add(note)
        await self.session.flush()
        return note

    async def get(self, note_id: uuid.UUID) -> Note | None:
        return await self.session.get(Note, note_id)

    async def list(self, idea_state: str | None = None, limit: int = 100) -> list[Note]:
        stmt = select(Note).order_by(Note.created_at.desc()).limit(limit)
        if idea_state is not None:
            stmt = stmt.where(Note.idea_state == idea_state)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, note_id: uuid.UUID, **fields) -> Note | None:
        note = await self.get(note_id)
        if note is None:
            return None
        for key, value in fields.items():
            setattr(note, key, value)
        await self.session.flush()
        return note

    async def delete(self, note_id: uuid.UUID) -> bool:
        result = await self.session.execute(delete(Note).where(Note.id == note_id))
        return result.rowcount > 0

    async def nearest(self, embedding: list[float], k: int = 5) -> list[Note]:
        """Return the k nearest notes to `embedding` by cosine distance, closest first."""
        stmt = (
            select(Note)
            .where(Note.embedding.is_not(None))
            .order_by(Note.embedding.cosine_distance(embedding))
            .limit(k)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
