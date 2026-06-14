"""POST /devices — Story 1.4 device-auth (APNs token registration).

Token-authed. Upserts on `apns_token` so re-registering the same device
(e.g. on every app launch) is idempotent — 201 for a new device, 200 for an
existing one with `last_seen` refreshed.
"""

import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_token
from app.db import get_session
from app.repositories.device import DeviceRepository
from app.schemas import DeviceIn, DeviceOut

logger = logging.getLogger("spore")

router = APIRouter()


@router.post("/devices", dependencies=[Depends(require_token)])
async def register_device(
    payload: DeviceIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    devices = DeviceRepository(session)
    device, created = await devices.register(payload.apns_token, platform=payload.platform)
    await session.commit()

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK

    logger.info(
        "device_registered",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "device_id": str(device.id),
            "was_created": created,
            "platform": device.platform,
        },
    )

    return {
        "ok": True,
        "data": DeviceOut.model_validate(device).model_dump(mode="json"),
        "error": None,
    }
