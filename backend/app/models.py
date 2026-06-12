"""SQLAlchemy 2.0 ORM models mapping the schema in migrations/001_init.sql.

Column names/types/defaults mirror 001_init.sql exactly. Server-generated
defaults (uuid_generate_v4(), now()) are declared with server_default so the
DB — not the ORM — produces them.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BOOLEAN,
    INTEGER,
    TEXT,
    TIMESTAMP,
    ForeignKey,
    Numeric,
    PrimaryKeyConstraint,
    REAL,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RawCapture(Base):
    __tablename__ = "raw_capture"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    source: Mapped[str] = mapped_column(TEXT, nullable=False)
    body: Mapped[str | None] = mapped_column(TEXT)
    media_url: Mapped[str | None] = mapped_column(TEXT)
    transcribed: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, server_default=text("false"))
    lang: Mapped[str | None] = mapped_column(TEXT)
    status: Mapped[str] = mapped_column(TEXT, nullable=False, server_default=text("'pending'"))
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class Note(Base):
    __tablename__ = "note"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    vault_path: Mapped[str | None] = mapped_column(TEXT, unique=True)
    title: Mapped[str | None] = mapped_column(TEXT)
    type: Mapped[str | None] = mapped_column(TEXT)
    domain: Mapped[str | None] = mapped_column(TEXT)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(TEXT), server_default=text("'{}'"))
    idea_state: Mapped[str | None] = mapped_column(TEXT, server_default=text("'seedling'"))
    confidence: Mapped[float | None] = mapped_column(REAL)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    source_capture_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_capture.id")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class NoteLink(Base):
    __tablename__ = "note_link"
    __table_args__ = (PrimaryKeyConstraint("src_id", "dst_id", "kind"),)

    src_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("note.id", ondelete="CASCADE")
    )
    dst_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("note.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(TEXT, nullable=False, server_default=text("'related'"))


class IdeaEvent(Base):
    __tablename__ = "idea_event"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("note.id", ondelete="CASCADE")
    )
    from_state: Mapped[str | None] = mapped_column(TEXT)
    to_state: Mapped[str] = mapped_column(TEXT, nullable=False)
    reason: Mapped[str | None] = mapped_column(TEXT)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class ReviewItem(Base):
    __tablename__ = "review_item"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    capture_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("raw_capture.id"))
    reason: Mapped[str | None] = mapped_column(TEXT)
    status: Mapped[str] = mapped_column(TEXT, nullable=False, server_default=text("'open'"))
    suggested_path: Mapped[str | None] = mapped_column(TEXT)
    suggested_type: Mapped[str | None] = mapped_column(TEXT)
    confidence: Mapped[float | None] = mapped_column(REAL)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class Correction(Base):
    __tablename__ = "correction"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    review_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("review_item.id"))
    original_json: Mapped[dict | None] = mapped_column(JSONB)
    corrected_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Reminder(Base):
    __tablename__ = "reminder"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("note.id", ondelete="CASCADE")
    )
    fire_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    channel: Mapped[str] = mapped_column(TEXT, nullable=False, server_default=text("'apns'"))
    recurrence: Mapped[str | None] = mapped_column(TEXT)
    status: Mapped[str] = mapped_column(TEXT, nullable=False, server_default=text("'scheduled'"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class SkillRun(Base):
    __tablename__ = "skill_run"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    skill: Mapped[str] = mapped_column(TEXT, nullable=False)
    note_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("note.id"))
    status: Mapped[str] = mapped_column(TEXT, nullable=False, server_default=text("'ok'"))
    output_path: Mapped[str | None] = mapped_column(TEXT)
    model: Mapped[str | None] = mapped_column(TEXT)
    tokens_in: Mapped[int | None] = mapped_column(INTEGER)
    tokens_out: Mapped[int | None] = mapped_column(INTEGER)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 5))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Device(Base):
    __tablename__ = "device"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    apns_token: Mapped[str | None] = mapped_column(TEXT, unique=True)
    platform: Mapped[str] = mapped_column(TEXT, nullable=False, server_default=text("'ios'"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    last_seen: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
