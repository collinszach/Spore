"""Repository for device rows (Story 1.4 device-auth / Epic 8 delivery).

`register` upserts on `apns_token` (unique) so repeated registration from
the same device is idempotent — `last_seen` is bumped on every call.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models import Device


class DeviceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def register(self, apns_token: str, platform: str = "ios") -> tuple[Device, bool]:
        """Upsert a device by `apns_token`. Returns (device, created)."""
        existing = await self.get_by_token(apns_token)

        stmt = (
            pg_insert(Device)
            .values(apns_token=apns_token, platform=platform, last_seen=func.now())
            .on_conflict_do_update(
                index_elements=[Device.apns_token],
                set_={"platform": platform, "last_seen": func.now()},
            )
            .returning(Device)
        )
        result = await self.session.execute(stmt)
        device = result.scalar_one()
        await self.session.flush()
        return device, existing is None

    async def get_by_token(self, apns_token: str) -> Device | None:
        result = await self.session.execute(select(Device).where(Device.apns_token == apns_token))
        return result.scalar_one_or_none()

    async def list_tokens(self) -> list[str]:
        """All registered APNs tokens (non-null)."""
        result = await self.session.execute(select(Device.apns_token).where(Device.apns_token.isnot(None)))
        return [row[0] for row in result.all()]
