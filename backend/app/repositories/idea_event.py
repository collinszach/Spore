"""Repository for idea_event rows (pipeline state-machine audit log)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdeaEvent


class IdeaEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        note_id: uuid.UUID | None,
        to_state: str,
        from_state: str | None = None,
        reason: str | None = None,
    ) -> IdeaEvent:
        event = IdeaEvent(
            note_id=note_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
        )
        self.session.add(event)
        await self.session.flush()
        return event
