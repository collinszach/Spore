"""POST /capture — Story 1.3.

Authed, idempotent capture intake. Router does no DB work directly; it
delegates to app.services.capture_service.
"""

import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_token
from app.db import get_session
from app.schemas import CaptureIn, CaptureOut
from app.services import capture_service

logger = logging.getLogger("spore")

router = APIRouter()


@router.post("/capture", dependencies=[Depends(require_token)])
async def create_capture(
    payload: CaptureIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    capture, created = await capture_service.ingest_capture(session, payload)

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK

    logger.info(
        "capture_ingested",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "capture_id": str(capture.id),
            "was_created": created,  # 'created' is a reserved LogRecord attribute
            "capture_source": capture.source,
        },
    )

    return {
        "ok": True,
        "data": CaptureOut.model_validate(capture).model_dump(mode="json"),
        "error": None,
    }
