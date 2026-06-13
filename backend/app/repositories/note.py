"""Repository for note rows, including pgvector kNN lookups."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note, NoteLink


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

    async def get_by_source_capture(self, capture_id: uuid.UUID) -> Note | None:
        """Return the note (if any) created from `capture_id`."""
        stmt = select(Note).where(Note.source_capture_id == capture_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

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

    async def list_by_state(self, idea_state: str, limit: int = 200) -> list[Note]:
        """Return notes in `idea_state`, most-recently-updated first."""
        stmt = (
            select(Note)
            .where(Note.idea_state == idea_state)
            .order_by(Note.updated_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_stale_seedlings(self, cutoff: datetime, limit: int = 200) -> list[Note]:
        """Return 'seedling' notes whose `updated_at` is older than `cutoff`."""
        stmt = (
            select(Note)
            .where(Note.idea_state == "seedling", Note.updated_at < cutoff)
            .order_by(Note.updated_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def incoming_link_counts(self, min_count: int) -> dict[uuid.UUID, int]:
        """Return {note_id: count} for notes with >= `min_count` incoming note_link rows.

        "Incoming" = rows where `note.id == note_link.dst_id` (backlinks).
        """
        stmt = (
            select(NoteLink.dst_id, func.count().label("ref_count"))
            .group_by(NoteLink.dst_id)
            .having(func.count() >= min_count)
        )
        result = await self.session.execute(stmt)
        return {row.dst_id: row.ref_count for row in result.all()}

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
