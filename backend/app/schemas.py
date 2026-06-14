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


class DeviceIn(BaseModel):
    """POST /devices request body (Story 1.4 device-auth)."""

    apns_token: str = Field(..., min_length=1)
    platform: str = "ios"


class DeviceOut(BaseModel):
    """Shape of a device row returned to clients."""

    id: uuid.UUID
    apns_token: str | None = None
    platform: str
    created_at: datetime
    last_seen: datetime | None = None

    model_config = {"from_attributes": True}


class ReviewItemOut(BaseModel):
    """Shape of a review_item row returned to clients (Story 4.2)."""

    id: uuid.UUID
    capture_id: uuid.UUID | None = None
    reason: str | None = None
    status: str
    suggested_path: str | None = None
    suggested_type: str | None = None
    confidence: float | None = None
    created_at: datetime
    resolved_at: datetime | None = None

    model_config = {"from_attributes": True}


class RedirectIn(BaseModel):
    """POST /review/{id}/redirect request body — user-supplied routing overrides (FR14).

    All fields optional; only the ones the user changed are sent. At least
    one field should be present for a meaningful redirect.
    """

    type: str | None = None
    domain: str | None = None
    tags: list[str] | None = None
    suggested_path: str | None = None


class MergeIn(BaseModel):
    """POST /review/{id}/merge request body — the existing note to merge into."""

    target_note_id: uuid.UUID


class PipelineMoveIn(BaseModel):
    """POST /pipeline/{note_id}/move request body (Story 7.1)."""

    to_state: str = Field(..., min_length=1)


class PipelineNoteOut(BaseModel):
    """Shape of a note row in pipeline list/move responses (Story 7.1)."""

    id: uuid.UUID
    title: str | None = None
    type: str | None = None
    idea_state: str | None = None
    domain: str | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}
