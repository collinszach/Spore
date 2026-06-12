"""GET /review and POST /review/{id}/{action} — Story 4.2 / 4.4.

Authed (device token). Router validates `action` and shapes the envelope;
all state-machine logic + side effects live in app.services.review_service.
"""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from agents.clients import EmbeddingsClient, get_embeddings_client
from app.auth import require_token
from app.db import get_session
from app.schemas import MergeIn, RedirectIn, ReviewItemOut
from app.services import review_service
from app.services.review_service import (
    VALID_ACTIONS,
    InvalidReviewAction,
    ReviewItemNotFound,
    ReviewItemNotOpen,
)
from app.vault import VaultWriter, get_vault_writer

logger = logging.getLogger("spore")

router = APIRouter()


def _get_embeddings_client() -> EmbeddingsClient:
    """FastAPI dependency wrapper so tests can override with a fake/spy."""
    return get_embeddings_client()


def _get_vault_writer() -> VaultWriter:
    """FastAPI dependency wrapper so tests can override with a fake/spy."""
    return get_vault_writer()


@router.get("/review", dependencies=[Depends(require_token)])
async def list_review_items(
    status: str | None = Query(default="open"),
    session: AsyncSession = Depends(get_session),
):
    items = await review_service.list_open(session, status=status)
    return {
        "ok": True,
        "data": [ReviewItemOut.model_validate(item).model_dump(mode="json") for item in items],
        "error": None,
    }


@router.post("/review/{review_id}/{action}", dependencies=[Depends(require_token)])
async def act_on_review_item(
    review_id: str,
    action: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    embeddings: EmbeddingsClient = Depends(_get_embeddings_client),
    vault_writer: VaultWriter = Depends(_get_vault_writer),
):
    if action not in VALID_ACTIONS:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "data": None, "error": f"unknown action: {action}"},
        )

    try:
        review_uuid = uuid.UUID(review_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "data": None, "error": f"invalid review_id: {review_id}"},
        )

    payload: dict | None = None
    if action == "redirect":
        body = await _read_json(request)
        payload = RedirectIn.model_validate(body or {}).model_dump()
    elif action == "merge":
        body = await _read_json(request)
        try:
            payload = MergeIn.model_validate(body or {}).model_dump()
        except Exception as exc:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "data": None, "error": str(exc)},
            )

    try:
        item = await review_service.apply_action(
            session,
            review_uuid,
            action,
            payload,
            embeddings=embeddings,
            vault_writer=vault_writer,
        )
    except ReviewItemNotFound:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "data": None, "error": "review item not found"},
        )
    except ReviewItemNotOpen as exc:
        return JSONResponse(
            status_code=409,
            content={"ok": False, "data": None, "error": f"review item is not open (status={exc})"},
        )
    except InvalidReviewAction as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "data": None, "error": str(exc)},
        )

    logger.info(
        "review_action_applied",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "review_id": str(review_uuid),
            "action": action,
            "status": item.status,
        },
    )

    return {
        "ok": True,
        "data": ReviewItemOut.model_validate(item).model_dump(mode="json"),
        "error": None,
    }


async def _read_json(request: Request) -> dict | None:
    """Best-effort JSON body read; returns None for empty bodies."""
    body_bytes = await request.body()
    if not body_bytes:
        return None
    return json.loads(body_bytes)
