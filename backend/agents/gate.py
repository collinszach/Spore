"""Confidence gate (ARCHITECTURE §5, ADR-003) — the core triage invariant.

`route()` is pure: given a capture id, a validated `TriageResult`, and an
embedding, it returns a `GateDecision` describing exactly which DB rows to
create. It performs NO I/O — the pipeline (agents/triage.py) executes the
decision against the repositories. This keeps the gate logic unit-testable
in isolation (see tests/test_triage.py).

Decision table (must match ARCHITECTURE §5 exactly):

| routing_confidence        | note row | review_item              | reminder (type=task) |
|----------------------------|----------|---------------------------|------------------------|
| >= DIRECT_WRITE_THRESHOLD   | yes, needs_review=False | no (unless dup) | always |
| REVIEW_FLOOR..threshold     | yes, needs_review=True, tags+=['needs-review'] | yes (low_confidence) | always |
| < REVIEW_FLOOR              | NO (vault untouched) | yes (low_confidence) | always |
| duplicate_of set            | (per above)            | + yes (duplicate)       | always |

Invariant: below REVIEW_FLOOR, no `note` row is created — the vault is never
touched (ARCHITECTURE §5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.config import settings
from agents.sorter import TriageResult

NEEDS_REVIEW_TAG = "needs-review"


@dataclass
class NotePlan:
    """Fields for the `note` row the pipeline should create."""

    type: str
    tags: list[str]
    domain: str | None
    confidence: float
    embedding: list[float]
    source_capture_id: uuid.UUID
    idea_state: str = "seedling"


@dataclass
class ReviewItemPlan:
    """Fields for a `review_item` row the pipeline should create."""

    capture_id: uuid.UUID
    reason: str
    confidence: float | None = None
    suggested_type: str | None = None


@dataclass
class ReminderPlan:
    """Fields for a `reminder` row the pipeline should create (FR15)."""

    note_id: uuid.UUID | None = None
    channel: str = "apns"
    status: str = "scheduled"
    hours_from_now: float = 24.0


@dataclass
class GateDecision:
    """The set of DB writes `route()` decided on. Pure data, no I/O."""

    create_note: NotePlan | None = None
    create_review_items: list[ReviewItemPlan] = field(default_factory=list)
    create_reminder: ReminderPlan | None = None


def route(
    capture_id: uuid.UUID,
    triage: TriageResult,
    embedding: list[float],
) -> GateDecision:
    """Decide DB writes for a triaged capture per ARCHITECTURE §5.

    `embedding` is the capture's own embedding (stored on the note row if one
    is created). `triage.duplicate_of` is honored as already-computed by the
    dedup step (agents/embeddings.py) and folded into `triage` by the caller.
    """
    decision = GateDecision()

    # Tasks always create a reminder, regardless of confidence (FR15).
    if triage.type == "task":
        decision.create_reminder = ReminderPlan()

    confidence = triage.routing_confidence

    if confidence >= settings.direct_write_threshold:
        decision.create_note = NotePlan(
            type=triage.type,
            tags=list(triage.tags),
            domain=triage.domain,
            confidence=confidence,
            embedding=embedding,
            source_capture_id=capture_id,
        )
    elif confidence >= settings.review_floor:
        tags = list(triage.tags)
        if NEEDS_REVIEW_TAG not in tags:
            tags.append(NEEDS_REVIEW_TAG)
        decision.create_note = NotePlan(
            type=triage.type,
            tags=tags,
            domain=triage.domain,
            confidence=confidence,
            embedding=embedding,
            source_capture_id=capture_id,
        )
        decision.create_review_items.append(
            ReviewItemPlan(
                capture_id=capture_id,
                reason="low_confidence",
                confidence=confidence,
                suggested_type=triage.type,
            )
        )
    else:
        # Below the floor: vault untouched, no note row.
        decision.create_review_items.append(
            ReviewItemPlan(
                capture_id=capture_id,
                reason="low_confidence",
                confidence=confidence,
                suggested_type=triage.type,
            )
        )

    if triage.duplicate_of is not None:
        decision.create_review_items.append(
            ReviewItemPlan(
                capture_id=capture_id,
                reason="duplicate",
                confidence=confidence,
                suggested_type=triage.type,
            )
        )

    return decision
