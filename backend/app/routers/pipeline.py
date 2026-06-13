"""GET /pipeline, POST /pipeline/{note_id}/move, GET /pipeline/suggestions
— Epic 7 Stories 7.1 / 7.3 / 7.4.

Token-authed via the shared `require_token` dependency. All state-machine
logic, persistence, and the promotion/stale rules live in
app.services.pipeline_service; this router only validates input and shapes
the `{ok,data,error}` envelope.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from app.auth import require_token
from app.db import get_session
from app.pipeline import ALLOWED_TRANSITIONS, ALL_STATES
from app.schemas import PipelineMoveIn, PipelineNoteOut
from app.services import pipeline_service
from app.services.pipeline_service import InvalidTransition, NoteNotFound

router = APIRouter()


@router.get("/pipeline", dependencies=[Depends(require_token)])
async def get_pipeline(session: AsyncSession = Depends(get_session)):
    grouped = await pipeline_service.list_by_state(session)
    return {
        "ok": True,
        "data": {
            "states": {
                state: [
                    PipelineNoteOut.model_validate(note).model_dump(mode="json")
                    for note in notes
                ]
                for state, notes in grouped["states"].items()
            },
            "counts": grouped["counts"],
        },
        "error": None,
    }


@router.get("/pipeline/suggestions", dependencies=[Depends(require_token)])
async def get_pipeline_suggestions(session: AsyncSession = Depends(get_session)):
    data = await pipeline_service.suggestions(session)
    return {
        "ok": True,
        "data": {
            "promotions": [
                {**p, "note_id": str(p["note_id"])} for p in data["promotions"]
            ],
            "stale": [
                {**s, "note_id": str(s["note_id"])} for s in data["stale"]
            ],
        },
        "error": None,
    }


@router.post("/pipeline/{note_id}/move", dependencies=[Depends(require_token)])
async def move_pipeline_note(
    note_id: str,
    body: PipelineMoveIn,
    session: AsyncSession = Depends(get_session),
):
    try:
        note_uuid = uuid.UUID(note_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "data": None, "error": f"invalid note_id: {note_id}"},
        )

    if body.to_state not in ALL_STATES:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "data": None, "error": f"unknown idea_state: {body.to_state}"},
        )

    try:
        note = await pipeline_service.move(session, note_uuid, body.to_state)
    except NoteNotFound:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "data": None, "error": "note not found"},
        )
    except InvalidTransition as exc:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "data": None,
                "error": {
                    "message": str(exc),
                    "current_state": exc.from_state,
                    "target_state": exc.to_state,
                    "allowed_transitions": sorted(ALLOWED_TRANSITIONS.get(exc.from_state or "", set())),
                },
            },
        )

    await session.commit()

    return {
        "ok": True,
        "data": PipelineNoteOut.model_validate(note).model_dump(mode="json"),
        "error": None,
    }
