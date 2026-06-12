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

from agents.clients import get_claude_client, get_embeddings_client
from agents.triage import triage_batch
from app.auth import require_token
from app.config import settings
from app.db import get_session

logger = logging.getLogger("spore")

router = APIRouter(prefix="/internal")


@router.post("/triage-batch", dependencies=[Depends(require_token)])
async def run_triage_batch(
    request: Request,
    limit: int = Query(default=None, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    batch_limit = limit or settings.triage_batch_limit

    claude = get_claude_client()
    embeddings = get_embeddings_client()

    summaries = await triage_batch(session, limit=batch_limit, claude=claude, embeddings=embeddings)

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
