"""POST /capture — Story 1.3. POST /capture/audio — Story 2.6 (voice capture).

Authed, idempotent capture intake. Router does no DB work directly; it
delegates to app.services.capture_service.
"""

import logging
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from agents.transcription import TranscriptionClient, get_transcription_client
from app.auth import require_token
from app.config import settings
from app.db import get_session
from app.schemas import CaptureIn, CaptureOut
from app.services import capture_service

logger = logging.getLogger("spore")

router = APIRouter()


def _get_transcription_client() -> TranscriptionClient:
    """FastAPI dependency wrapper so tests can override with a fake/spy."""
    return get_transcription_client()


def _audio_extension(upload: UploadFile) -> str:
    """Derive a file extension from the upload's filename or content-type."""
    if upload.filename and "." in upload.filename:
        ext = os.path.splitext(upload.filename)[1]
        if ext:
            return ext
    content_type = upload.content_type or ""
    content_type_ext = {
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/m4a": ".m4a",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
    }
    return content_type_ext.get(content_type, ".m4a")


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


@router.post("/capture/audio", dependencies=[Depends(require_token)])
async def create_voice_capture(
    request: Request,
    response: Response,
    capture_uuid: uuid.UUID = Form(...),
    source: str = Form(default="ios_voice"),
    lang: str | None = Form(default=None),
    audio: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    transcription_client: TranscriptionClient = Depends(_get_transcription_client),
):
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty audio file")

    ext = _audio_extension(audio)
    os.makedirs(settings.media_dir, exist_ok=True)
    media_path = os.path.join(settings.media_dir, f"{capture_uuid}{ext}")
    with open(media_path, "wb") as f:
        f.write(audio_bytes)

    transcript = await transcription_client.transcribe(audio_bytes, audio.filename or f"{capture_uuid}{ext}")

    capture, created = await capture_service.ingest_voice_capture(
        session,
        capture_uuid=capture_uuid,
        source=source,
        transcript=transcript,
        media_url=media_path,
        lang=lang,
    )

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK

    logger.info(
        "voice_capture_ingested",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "capture_id": str(capture.id),
            "was_created": created,
            "capture_source": capture.source,
        },
    )

    return {
        "ok": True,
        "data": CaptureOut.model_validate(capture).model_dump(mode="json"),
        "error": None,
    }
