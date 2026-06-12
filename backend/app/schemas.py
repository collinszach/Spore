"""Pydantic request/response schemas for the API (Story 1.3+).

These wrap the ORM models in `app.models` for HTTP I/O — validated input
shapes for routers, kept separate from SQLAlchemy models.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CaptureIn(BaseModel):
    """POST /capture request body.

    `capture_uuid` is client-generated and used directly as `raw_capture.id`
    (see app.services.capture_service) to give idempotency via the PK.
    """

    capture_uuid: uuid.UUID
    source: str = Field(..., min_length=1)
    body: str | None = None
    media_url: str | None = None
    lang: str | None = None
    device_id: uuid.UUID | None = None


class CaptureOut(BaseModel):
    """Shape of a raw_capture row returned to clients."""

    id: uuid.UUID
    source: str
    body: str | None = None
    media_url: str | None = None
    transcribed: bool
    lang: str | None = None
    status: str
    device_id: uuid.UUID | None = None
    created_at: datetime
    processed_at: datetime | None = None

    model_config = {"from_attributes": True}
