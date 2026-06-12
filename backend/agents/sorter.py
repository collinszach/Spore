"""Sorter agent (Epic 3 / ARCHITECTURE §4) — classify a capture.

`classify()` builds a typed prompt from the capture body and its kNN
neighbor notes (for related_ids / duplicate_of context), calls the Claude
client, and strictly validates the response into a `TriageResult`. Invalid
JSON never reaches the database — `classify` raises rather than passing
unvalidated data downstream.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from agents.clients import ClaudeClient, ClaudeResponse
from app.models import Note, RawCapture

TriageType = Literal["fleeting", "project_idea", "task", "reference", "question", "journal"]

_VALID_TYPES = {"fleeting", "project_idea", "task", "reference", "question", "journal"}


class TriageResult(BaseModel):
    """Validated Sorter output (FR8/FR10/FR11/FR12)."""

    type: TriageType
    tags: list[str] = Field(default_factory=list)
    domain: str | None = None
    urgency: str | None = None
    actionability: str | None = None
    routing_confidence: float
    related_ids: list[uuid.UUID] = Field(default_factory=list)
    duplicate_of: uuid.UUID | None = None

    @field_validator("routing_confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class SorterError(Exception):
    """Raised when the Claude client returns invalid/unparseable JSON."""


def _build_prompt(capture: RawCapture, neighbors: list[Note]) -> tuple[str, str]:
    system = (
        "You are the Sorter agent for Spore, a personal knowledge capture system. "
        "Classify the given capture and return ONLY a JSON object with exactly these "
        "fields: type (one of: fleeting, project_idea, task, reference, question, "
        "journal), tags (list of short strings), domain (string or null), "
        "urgency (string or null), actionability (string or null), "
        "routing_confidence (float 0-1), related_ids (list of UUID strings of "
        "neighbor notes this capture is related to, may be empty), duplicate_of "
        "(UUID string of a neighbor note this capture duplicates, or null). "
        "No prose, no markdown — JSON only. "
        "Respond with only the JSON object, no prose, no code fences."
    )

    neighbor_lines = []
    for note in neighbors:
        title = note.title or "(untitled)"
        neighbor_lines.append(f"- id={note.id} type={note.type} title={title!r}")
    neighbors_block = "\n".join(neighbor_lines) if neighbor_lines else "(none)"

    user = (
        f"Capture body:\n{capture.body or ''}\n\n"
        f"Candidate related notes (from kNN search):\n{neighbors_block}\n\n"
        "Return the JSON object now."
    )
    return system, user


async def classify(capture: RawCapture, neighbors: list[Note], *, claude: ClaudeClient) -> TriageResult:
    """Classify `capture` using `claude`, validated strictly into a TriageResult.

    Raises `SorterError` if the model response is missing, not valid JSON,
    or fails schema validation — callers must not let unvalidated data reach
    the DB.
    """
    result, _response = await classify_with_response(capture, neighbors, claude=claude)
    return result


async def classify_with_response(
    capture: RawCapture, neighbors: list[Note], *, claude: ClaudeClient
) -> tuple[TriageResult, ClaudeResponse]:
    """Like `classify`, but also returns the raw `ClaudeResponse` (for token
    usage / cost-ledger purposes in the triage pipeline)."""
    system, user = _build_prompt(capture, neighbors)
    response = await claude.complete(system, user)

    if response.json is None:
        raise SorterError(f"Sorter response was not valid JSON: {response.text!r}")

    try:
        result = TriageResult.model_validate(response.json)
    except ValidationError as exc:
        raise SorterError(f"Sorter response failed schema validation: {exc}") from exc

    return result, response
