"""Triage pipeline (ARCHITECTURE §4 sequence, FR8-FR12/FR15/FR36).

`triage_capture` runs the full per-capture sequence:

    embed -> pgvector kNN -> Sorter.classify -> validate
      -> dedup -> confidence gate -> write rows -> mark triaged
      -> write one skill_run row

`triage_batch` selects pending captures FIFO and triages each (FR36 —
batched triage to amortize cost).

Epic 5: when the gate creates a `note` row (direct-write or needs-review —
i.e. `decision.create_note is not None`), the note is also written to the
Obsidian vault via `vault_writer.write_note(...)` (FR16-FR19) and the
returned relative path is persisted onto `note.vault_path`. Below-floor
captures (`decision.create_note is None`) never call the vault writer —
this preserves the confidence-gate invariant that the vault is untouched
below REVIEW_FLOOR (ARCHITECTURE §5).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents import gate
from agents.clients import ClaudeClient, EmbeddingsClient
from agents.embeddings import embed_capture, find_duplicate, nearest_neighbors
from agents.feedback import format_fewshot_block, recent_correction_examples
from agents.sorter import TriageResult, classify_with_response
from app.config import settings
from app.models import RawCapture
from app.repositories.capture import CaptureRepository
from app.repositories.note import NoteRepository
from app.repositories.reminder import ReminderRepository
from app.repositories.review import ReviewRepository
from app.repositories.skill_run import SkillRunRepository
from app.vault import VaultWriter, get_vault_writer
from app.vault_adapter import note_to_doc

# Per-million-token pricing (USD) for known Sorter models. Unknown models
# (including fake clients) cost $0 — cost discipline (CLAUDE.md rule 7) only
# applies to real API calls.
_MODEL_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    # (input $/Mtok, output $/Mtok)
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}


def _estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    pricing = _MODEL_PRICING_PER_MTOK.get(model)
    if pricing is None:
        return Decimal("0")
    in_price, out_price = pricing
    cost = (tokens_in / 1_000_000) * in_price + (tokens_out / 1_000_000) * out_price
    return Decimal(str(round(cost, 5)))


async def triage_capture(
    session: AsyncSession,
    capture: RawCapture,
    *,
    claude: ClaudeClient,
    embeddings: EmbeddingsClient,
    vault_writer: VaultWriter | None = None,
) -> dict:
    """Run the full triage sequence for one capture. Returns a summary dict."""
    vault_writer = vault_writer or get_vault_writer()
    note_repo = NoteRepository(session)
    capture_repo = CaptureRepository(session)
    review_repo = ReviewRepository(session)
    reminder_repo = ReminderRepository(session)
    skill_run_repo = SkillRunRepository(session)

    # 1. Embed the capture body.
    embedding = await embed_capture(capture.body or "", embeddings=embeddings)

    # 2. pgvector kNN for related-note candidates.
    neighbors = await nearest_neighbors(session, embedding, k=5)

    # 3. Sorter classification, strictly validated. Story 9.2/FR37: when
    # enabled, append a short few-shot block built from recent corrections.
    fewshot_block: str | None = None
    if settings.sorter_fewshot_enabled:
        examples = await recent_correction_examples(session, k=settings.sorter_fewshot_k)
        fewshot_block = format_fewshot_block(examples) or None

    triage: TriageResult
    triage, claude_response = await classify_with_response(
        capture, neighbors, claude=claude, fewshot_block=fewshot_block
    )

    # 4. Near-duplicate detection (FR11) — fold into the triage result if the
    # Sorter didn't already flag one.
    if triage.duplicate_of is None:
        dup_id = find_duplicate(embedding, neighbors)
        if dup_id is not None:
            triage = triage.model_copy(update={"duplicate_of": dup_id})

    # 5. Confidence gate — pure decision.
    decision = gate.route(capture.id, triage, embedding)

    created_note_id: uuid.UUID | None = None
    created_review_item_ids: list[uuid.UUID] = []
    created_reminder_id: uuid.UUID | None = None

    if decision.create_note is not None:
        plan = decision.create_note
        body = capture.body or ""
        title = body.splitlines()[0].strip() if body.strip() else None
        title = title[:200] if title else None

        note = await note_repo.create(
            title=title,
            type=plan.type,
            tags=plan.tags,
            domain=plan.domain,
            idea_state=plan.idea_state,
            confidence=plan.confidence,
            embedding=plan.embedding,
            source_capture_id=plan.source_capture_id,
        )
        created_note_id = note.id

        # Epic 5: every note the gate creates (direct-write or
        # needs-review) is written to the vault immediately (FR16-FR19).
        # Below-floor captures never reach this branch.
        doc = await note_to_doc(session, note, body=body)
        vault_path = await vault_writer.write_note(doc)
        note = await note_repo.update(note.id, vault_path=vault_path)
        assert note is not None

    for review_plan in decision.create_review_items:
        review_item = await review_repo.create(
            capture_id=review_plan.capture_id,
            reason=review_plan.reason,
            confidence=review_plan.confidence,
            suggested_type=review_plan.suggested_type,
        )
        created_review_item_ids.append(review_item.id)

    if decision.create_reminder is not None:
        reminder_plan = decision.create_reminder
        fire_at = datetime.now(timezone.utc) + timedelta(hours=reminder_plan.hours_from_now)
        reminder = await reminder_repo.create(
            note_id=created_note_id,
            fire_at=fire_at,
            channel=reminder_plan.channel,
            status=reminder_plan.status,
        )
        created_reminder_id = reminder.id

    # 6. Mark capture triaged.
    await capture_repo.update(
        capture.id,
        status="triaged",
        processed_at=datetime.now(timezone.utc),
    )

    # 7. One skill_run row per capture (cost ledger, CLAUDE.md rule 7).
    tokens_in = claude_response.usage.input_tokens
    tokens_out = claude_response.usage.output_tokens
    model = claude_response.model
    cost_usd = _estimate_cost_usd(model, tokens_in, tokens_out)

    await skill_run_repo.create(
        skill="sorter",
        note_id=created_note_id,
        status="ok",
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )

    return {
        "capture_id": capture.id,
        "type": triage.type,
        "routing_confidence": triage.routing_confidence,
        "duplicate_of": triage.duplicate_of,
        "note_id": created_note_id,
        "review_item_ids": created_review_item_ids,
        "reminder_id": created_reminder_id,
    }


async def triage_batch(
    session: AsyncSession,
    *,
    limit: int,
    claude: ClaudeClient,
    embeddings: EmbeddingsClient,
    vault_writer: VaultWriter | None = None,
) -> list[dict]:
    """Triage up to `limit` pending captures, FIFO (FR36)."""
    stmt = (
        select(RawCapture)
        .where(RawCapture.status == "pending")
        .order_by(RawCapture.created_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    captures = list(result.scalars().all())

    vault_writer = vault_writer or get_vault_writer()

    summaries = []
    for capture in captures:
        summary = await triage_capture(
            session, capture, claude=claude, embeddings=embeddings, vault_writer=vault_writer
        )
        summaries.append(summary)

    await session.commit()
    return summaries
