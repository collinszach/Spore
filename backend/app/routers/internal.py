"""Internal/cron-facing endpoints (ARCHITECTURE §7 n8n flows).

Token-authed via the same `require_token` dependency as capture-surface
endpoints. `POST /internal/triage-batch` runs the Epic 3 triage pipeline
against pending captures; n8n's `triage-cron` flow calls this on a 1-2 min
schedule. Uses real-or-fake provider clients depending on whether
VOYAGE_API_KEY / ANTHROPIC_API_KEY are configured (agents.clients factories).
"""

import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from agents import curator
from agents.clients import get_claude_client, get_embeddings_client
from agents.triage import triage_batch
from app.auth import require_token
from app.config import settings
from app.db import get_session
from app.notify import Notifier, get_notifier
from app.repositories.correction import CorrectionRepository
from app.repositories.device import DeviceRepository
from app.services import ops_service, pipeline_service
from app.services.resurface_service import fire_due_reminders, resurface_due_notes
from app.vault import VaultWriter, get_vault_writer

logger = logging.getLogger("spore")

router = APIRouter(prefix="/internal")


def _get_vault_writer() -> VaultWriter:
    """FastAPI dependency wrapper so tests can override with a fake/spy."""
    return get_vault_writer()


def _get_notifier(session: AsyncSession = Depends(get_session)) -> Notifier:
    """FastAPI dependency wrapper so tests can override with a SpyNotifier (Epic 8).

    Binds the request's session into a `token_provider` so `ApnsNotifier`
    (when APNs is configured) can fetch registered device tokens without a
    global session — see app.notify module docstring.
    """

    async def _token_provider() -> list[str]:
        return await DeviceRepository(session).list_tokens()

    return get_notifier(token_provider=_token_provider)


@router.post("/triage-batch", dependencies=[Depends(require_token)])
async def run_triage_batch(
    request: Request,
    limit: int = Query(default=None, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    vault_writer: VaultWriter = Depends(_get_vault_writer),
):
    batch_limit = limit or settings.triage_batch_limit

    claude = get_claude_client()
    embeddings = get_embeddings_client()

    summaries = await triage_batch(
        session, limit=batch_limit, claude=claude, embeddings=embeddings, vault_writer=vault_writer
    )

    logger.info(
        "triage_batch_completed",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "batch_size": len(summaries),
            "batch_limit": batch_limit,
        },
    )

    return {
        "ok": True,
        "data": {
            "count": len(summaries),
            "results": [
                {
                    "capture_id": str(s["capture_id"]),
                    "type": s["type"],
                    "routing_confidence": s["routing_confidence"],
                    "duplicate_of": str(s["duplicate_of"]) if s["duplicate_of"] else None,
                    "note_id": str(s["note_id"]) if s["note_id"] else None,
                    "review_item_ids": [str(rid) for rid in s["review_item_ids"]],
                    "reminder_id": str(s["reminder_id"]) if s["reminder_id"] else None,
                }
                for s in summaries
            ],
        },
        "error": None,
    }


@router.post("/stale-sweep", dependencies=[Depends(require_token)])
async def run_stale_sweep(session: AsyncSession = Depends(get_session)):
    """Return the current stale-'seedling' set (Story 7.4).

    n8n's daily digest flow calls this on a schedule. Currently read-only —
    the response is the same `stale` shape as GET /pipeline/suggestions;
    repeated calls are naturally idempotent since no rows are written.
    """
    stale = await pipeline_service.stale_seedling_suggestions(session)
    return {
        "ok": True,
        "data": {
            "stale": [{**s, "note_id": str(s["note_id"])} for s in stale],
        },
        "error": None,
    }


@router.post("/reminder-fire", dependencies=[Depends(require_token)])
async def run_reminder_fire(
    session: AsyncSession = Depends(get_session),
    notifier: Notifier = Depends(_get_notifier),
):
    """Fire all due reminders (Story 8.1, FR30).

    n8n's `reminder-fire` flow calls this every minute. For each due
    reminder (status='scheduled', fire_at <= now): notify, then advance per
    `recurrence` (null -> fired; daily/weekly/spaced -> advance, stay
    scheduled). Returns the list of reminders that fired.
    """
    fired = await fire_due_reminders(session, notifier)
    return {
        "ok": True,
        "data": {
            "count": len(fired),
            "reminders": [
                {
                    "id": str(r.id),
                    "note_id": str(r.note_id) if r.note_id else None,
                    "channel": r.channel,
                    "recurrence": r.recurrence,
                    "fire_at": r.fire_at.isoformat(),
                }
                for r in fired
            ],
        },
        "error": None,
    }


@router.get("/resurface", dependencies=[Depends(require_token)])
async def get_resurface(session: AsyncSession = Depends(get_session)):
    """Notes due to resurface per the spaced schedule (Story 8.2, FR31).

    A note is due when floor(days since note.created_at) is in
    settings.resurface_schedule_days (default [1,3,7,30]) and its
    idea_state is not shipped/archived. Pure read.
    """
    due = await resurface_due_notes(session)
    return {
        "ok": True,
        "data": {
            "count": len(due),
            "notes": [
                {
                    "id": str(n["id"]),
                    "title": n["title"],
                    "type": n["type"],
                    "days_since": n["days_since"],
                    "bucket": n["bucket"],
                }
                for n in due
            ],
        },
        "error": None,
    }


@router.get("/digest/daily", dependencies=[Depends(require_token)])
async def get_daily_digest(
    session: AsyncSession = Depends(get_session),
    notifier: Notifier = Depends(_get_notifier),
):
    """Daily digest (Story 8.3, FR32). n8n's `daily-digest` flow calls this at 07:00."""
    payload = await curator.daily_digest(session)

    resurfaced = payload["resurfaced_idea"]
    await notifier.send(
        channel="digest-daily",
        title="Spore daily digest",
        body=f"Review queue: {payload['review_queue_count']}; "
        f"reminders today: {len(payload['todays_reminders'])}",
        meta={"resurfaced_idea": str(resurfaced["id"]) if resurfaced else None},
    )

    data = {
        "review_queue_count": payload["review_queue_count"],
        "todays_reminders": [
            {
                "id": str(r["id"]),
                "note_id": str(r["note_id"]) if r["note_id"] else None,
                "fire_at": r["fire_at"].isoformat(),
                "channel": r["channel"],
                "recurrence": r["recurrence"],
            }
            for r in payload["todays_reminders"]
        ],
        "resurfaced_idea": (
            {
                "id": str(resurfaced["id"]),
                "title": resurfaced["title"],
                "type": resurfaced["type"],
                "days_since": resurfaced["days_since"],
                "bucket": resurfaced["bucket"],
            }
            if resurfaced
            else None
        ),
    }
    if "narrative" in payload:
        data["narrative"] = payload["narrative"]

    return {"ok": True, "data": data, "error": None}


@router.get("/digest/weekly", dependencies=[Depends(require_token)])
async def get_weekly_digest(
    session: AsyncSession = Depends(get_session),
    notifier: Notifier = Depends(_get_notifier),
):
    """Weekly digest (Story 8.3, FR33). n8n's `weekly-review` flow calls this Sundays."""
    payload = await curator.weekly_digest(session)

    await notifier.send(
        channel="digest-weekly",
        title="Spore weekly review",
        body=f"Orphans: {len(payload['orphan_notes'])}; "
        f"promotion-ready: {len(payload['promotion_ready'])}; "
        f"stale: {len(payload['stale'])}",
        meta=None,
    )

    data = {
        "orphan_notes": [
            {"id": str(n["id"]), "title": n["title"], "type": n["type"], "idea_state": n["idea_state"]}
            for n in payload["orphan_notes"]
        ],
        "dangling_links": [
            {"src_id": str(link["src_id"]), "dst_id": str(link["dst_id"]), "kind": link["kind"]}
            for link in payload["dangling_links"]
        ],
        "promotion_ready": [
            {**p, "note_id": str(p["note_id"])} for p in payload["promotion_ready"]
        ],
        "stale": [{**s, "note_id": str(s["note_id"])} for s in payload["stale"]],
    }
    if "narrative" in payload:
        data["narrative"] = payload["narrative"]

    return {"ok": True, "data": data, "error": None}


@router.get("/cost", dependencies=[Depends(require_token)])
async def get_cost(session: AsyncSession = Depends(get_session)):
    """Cost dashboard (Story 9.1, FR35) — aggregates over `skill_run`."""
    data = await ops_service.cost_summary(session)
    return {"ok": True, "data": data, "error": None}


@router.get("/metrics", dependencies=[Depends(require_token)])
async def get_metrics(session: AsyncSession = Depends(get_session)):
    """Ops/observability metrics (Story 9.3, ARCHITECTURE §9)."""
    data = await ops_service.ops_metrics(session)
    return {"ok": True, "data": data, "error": None}


@router.get("/corrections/summary", dependencies=[Depends(require_token)])
async def get_corrections_summary(
    k: int = Query(default=10, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """Corrections feedback summary (Story 9.2, FR37) — count + recent pairs."""
    correction_repo = CorrectionRepository(session)
    count = await correction_repo.count()
    recent = await correction_repo.list_recent(limit=k)

    return {
        "ok": True,
        "data": {
            "count": count,
            "recent": [
                {
                    "original_json": row.original_json,
                    "corrected_json": row.corrected_json,
                    "created_at": row.created_at.isoformat(),
                }
                for row in recent
            ],
        },
        "error": None,
    }
