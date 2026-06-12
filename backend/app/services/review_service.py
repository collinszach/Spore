"""Service layer for the native review queue (Story 4.2) + corrections (4.4).

Implements the four review actions — approve / redirect / merge / discard —
per ARCHITECTURE §6 and PRD FR13/FR14. Routers call `list_open` and
`apply_action`; this module owns the state-machine + side effects, using the
repositories for all DB access.

Action -> state/side-effect summary:

| action   | precondition | status ->   | note                                                  | correction | vault_writer | idea_event |
|----------|--------------|-------------|--------------------------------------------------------|------------|---------------|------------|
| approve  | open         | approved    | ensure exists (create if missing, remove needs-review) | no         | write_note    | seedling/manual |
| redirect | open         | redirected  | ensure exists with corrected type/tags                  | yes        | write_note    | no |
| merge    | open         | merged      | delete needs-review note (if any)                       | yes*       | no            | no |
| discard  | open         | discarded   | delete needs-review note (if any)                       | no         | no            | no |

* merge writes a `correction` row recording `{merged_into_note_id}` only when
  a mirror note existed for this capture (so the linkage to `target_note_id`
  survives the mirror-note delete; `note_link` rows would cascade-delete with
  the deleted note).

Errors are raised as the typed exceptions below; the router maps them to
HTTP status codes (404 / 409 / 400).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from agents.clients import EmbeddingsClient
from agents.embeddings import embed_capture
from app.models import Note, ReviewItem
from app.repositories.capture import CaptureRepository
from app.repositories.correction import CorrectionRepository
from app.repositories.idea_event import IdeaEventRepository
from app.repositories.note import NoteRepository
from app.repositories.review import ReviewRepository
from app.vault import VaultWriter

NEEDS_REVIEW_TAG = "needs-review"

VALID_ACTIONS = {"approve", "redirect", "merge", "discard"}


class ReviewItemNotFound(Exception):
    """No review_item with the given id."""


class ReviewItemNotOpen(Exception):
    """The review_item is not in 'open' status (already resolved)."""


class InvalidReviewAction(Exception):
    """Unknown action, or a required field is missing for the action."""


async def list_open(session: AsyncSession, status: str | None = "open") -> list[ReviewItem]:
    """List review_items, defaulting to status='open'."""
    repo = ReviewRepository(session)
    return await repo.list_by_status(status=status)


async def apply_action(
    session: AsyncSession,
    review_id: uuid.UUID,
    action: str,
    payload: dict | None,
    *,
    embeddings: EmbeddingsClient,
    vault_writer: VaultWriter,
) -> ReviewItem:
    """Apply `action` to the review_item `review_id` and commit the result.

    `payload` is the request body as a dict (RedirectIn/MergeIn.model_dump()
    for redirect/merge, ignored for approve/discard).
    """
    if action not in VALID_ACTIONS:
        raise InvalidReviewAction(f"unknown action: {action}")

    review_repo = ReviewRepository(session)
    item = await review_repo.get(review_id)
    if item is None:
        raise ReviewItemNotFound(str(review_id))
    if item.status != "open":
        raise ReviewItemNotOpen(item.status)

    if action == "approve":
        await _approve(session, item, embeddings=embeddings, vault_writer=vault_writer)
    elif action == "redirect":
        await _redirect(session, item, payload or {}, embeddings=embeddings, vault_writer=vault_writer)
    elif action == "merge":
        await _merge(session, item, payload or {})
    elif action == "discard":
        await _discard(session, item)

    await session.commit()
    refreshed = await review_repo.get(review_id)
    assert refreshed is not None
    return refreshed


# ── Action implementations ──────────────────────────────────────────────


async def _approve(
    session: AsyncSession,
    item: ReviewItem,
    *,
    embeddings: EmbeddingsClient,
    vault_writer: VaultWriter,
) -> None:
    note = await _ensure_note(session, item, embeddings=embeddings)

    if note.tags and NEEDS_REVIEW_TAG in note.tags:
        new_tags = [t for t in note.tags if t != NEEDS_REVIEW_TAG]
        note_repo = NoteRepository(session)
        note = await note_repo.update(note.id, tags=new_tags)
        assert note is not None

    await vault_writer.write_note(note)

    idea_event_repo = IdeaEventRepository(session)
    await idea_event_repo.create(note_id=note.id, to_state="seedling", reason="manual")

    review_repo = ReviewRepository(session)
    await review_repo.set_status(item.id, "approved", resolved_at=_now())


async def _redirect(
    session: AsyncSession,
    item: ReviewItem,
    payload: dict,
    *,
    embeddings: EmbeddingsClient,
    vault_writer: VaultWriter,
) -> None:
    original_json = {
        "suggested_type": item.suggested_type,
        "suggested_path": item.suggested_path,
        "confidence": item.confidence,
        "reason": item.reason,
    }
    corrected_json = {k: v for k, v in payload.items() if v is not None}

    correction_repo = CorrectionRepository(session)
    await correction_repo.create(
        review_item_id=item.id,
        original_json=original_json,
        corrected_json=corrected_json,
    )

    overrides: dict = {}
    if "type" in corrected_json:
        overrides["type"] = corrected_json["type"]
    if "domain" in corrected_json:
        overrides["domain"] = corrected_json["domain"]
    if "tags" in corrected_json:
        overrides["tags"] = corrected_json["tags"]

    note = await _ensure_note(session, item, embeddings=embeddings, overrides=overrides)

    if overrides:
        note_repo = NoteRepository(session)
        updated = await note_repo.update(note.id, **overrides)
        assert updated is not None
        note = updated

    await vault_writer.write_note(note)

    review_repo = ReviewRepository(session)
    await review_repo.set_status(item.id, "redirected", resolved_at=_now())


async def _merge(session: AsyncSession, item: ReviewItem, payload: dict) -> None:
    target_note_id = payload.get("target_note_id")
    if target_note_id is None:
        raise InvalidReviewAction("merge requires target_note_id")
    if isinstance(target_note_id, str):
        target_note_id = uuid.UUID(target_note_id)

    note_repo = NoteRepository(session)
    target_note = await note_repo.get(target_note_id)
    if target_note is None:
        raise InvalidReviewAction(f"target_note_id not found: {target_note_id}")

    if item.capture_id is not None:
        existing_note = await note_repo.get_by_source_capture(item.capture_id)
        if existing_note is not None:
            # `note_link` rows cascade-delete with either endpoint note, so a
            # link from the (about-to-be-deleted) duplicate note wouldn't
            # persist. Record the merge linkage durably as a `correction` row
            # instead, then delete the duplicate mirror note.
            correction_repo = CorrectionRepository(session)
            await correction_repo.create(
                review_item_id=item.id,
                original_json={
                    "suggested_type": item.suggested_type,
                    "suggested_path": item.suggested_path,
                    "confidence": item.confidence,
                    "reason": item.reason,
                    "note_id": str(existing_note.id),
                },
                corrected_json={"merged_into_note_id": str(target_note_id)},
            )
            await note_repo.delete(existing_note.id)
        # Below-the-floor case: no note row was ever created for this
        # capture, so there's nothing to link or delete — just resolve.

    review_repo = ReviewRepository(session)
    await review_repo.set_status(item.id, "merged", resolved_at=_now())


async def _discard(session: AsyncSession, item: ReviewItem) -> None:
    if item.capture_id is not None:
        note_repo = NoteRepository(session)
        existing_note = await note_repo.get_by_source_capture(item.capture_id)
        if existing_note is not None:
            await note_repo.delete(existing_note.id)

    review_repo = ReviewRepository(session)
    await review_repo.set_status(item.id, "discarded", resolved_at=_now())


# ── Helpers ────────────────────────────────────────────────────────────


async def _ensure_note(
    session: AsyncSession,
    item: ReviewItem,
    *,
    embeddings: EmbeddingsClient,
    overrides: dict | None = None,
) -> Note:
    """Return the note for `item.capture_id`, creating it if missing.

    The <0.50-floor case has no note row yet (vault untouched per the
    confidence gate invariant); approve/redirect create one here from the
    capture body, embedding it for search.
    """
    note_repo = NoteRepository(session)
    capture_id = item.capture_id

    note: Note | None = None
    if capture_id is not None:
        note = await note_repo.get_by_source_capture(capture_id)

    if note is not None:
        return note

    capture_repo = CaptureRepository(session)
    capture = await capture_repo.get(capture_id) if capture_id is not None else None
    body = (capture.body if capture else None) or ""

    title = body.splitlines()[0].strip() if body.strip() else None
    title = title[:200] if title else None

    overrides = overrides or {}
    note_type = overrides.get("type", item.suggested_type)
    domain = overrides.get("domain")
    tags = overrides.get("tags", [])

    embedding = await embed_capture(body, embeddings=embeddings)

    note = await note_repo.create(
        title=title,
        type=note_type,
        domain=domain,
        tags=tags,
        idea_state="seedling",
        confidence=item.confidence,
        embedding=embedding,
        source_capture_id=capture_id,
    )
    return note


def _now() -> datetime:
    return datetime.now(timezone.utc)
