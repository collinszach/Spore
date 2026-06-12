"""POST /skills/{name}/run — manual skill invocation (Epic 6, Story 6.2/6.3).

Token-authed (same `require_token` dependency as other capture-surface
endpoints). Loads the named skill from the declarative registry
(`agents.skills_registry.load_skills`, Story 6.1), loads the target note,
and runs it through the Builder (`agents.builder.run_skill`, Story 6.2).

Scheduled/on-state triggers (Story 6.5) are deferred — this is the manual
trigger only.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from agents.builder import run_skill
from agents.clients import ClaudeClient, get_claude_client
from agents.skills_registry import load_skills
from app.auth import require_token
from app.config import settings
from app.db import get_session
from app.repositories.note import NoteRepository
from app.vault import VaultWriter, get_vault_writer

logger = logging.getLogger("spore")

router = APIRouter(prefix="/skills")


class SkillRunIn(BaseModel):
    note_id: uuid.UUID


def _get_vault_writer() -> VaultWriter:
    """FastAPI dependency wrapper so tests can override with a fake/spy."""
    return get_vault_writer()


def _get_builder_claude_client() -> ClaudeClient:
    """FastAPI dependency wrapper so tests can override with a fake/spy.

    Uses `settings.builder_model` (a stronger model than the Sorter's,
    CLAUDE.md rule 7 — "stronger model only for build-out").
    """
    return get_claude_client(model=settings.builder_model)


@router.post("/{name}/run", dependencies=[Depends(require_token)])
async def run_skill_endpoint(
    name: str,
    body: SkillRunIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    claude: ClaudeClient = Depends(_get_builder_claude_client),
    vault_writer: VaultWriter = Depends(_get_vault_writer),
):
    skills = load_skills(settings.skills_dir)
    skill = skills.get(name)
    if skill is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "data": None, "error": f"unknown skill: {name}"},
        )

    note_repo = NoteRepository(session)
    note = await note_repo.get(body.note_id)
    if note is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "data": None, "error": f"note not found: {body.note_id}"},
        )

    summary = await run_skill(session, skill, note, claude=claude, vault_writer=vault_writer)
    await session.commit()

    logger.info(
        "skill_run_completed",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "skill": summary["skill"],
            "note_id": str(summary["note_id"]),
            "status": summary["status"],
        },
    )

    return {
        "ok": True,
        "data": {
            "skill": summary["skill"],
            "note_id": str(summary["note_id"]),
            "output_path": summary["output_path"],
            "status": summary["status"],
        },
        "error": None,
    }
