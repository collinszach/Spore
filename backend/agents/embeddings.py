"""Embeddings + dedup helpers for the triage pipeline (FR10/FR11, ADR-002).

`embed_capture` embeds the capture body (1024-dim). `nearest_neighbors` runs
`NoteRepository.nearest()` for related-note candidates. `find_duplicate`
checks whether the top neighbor is a near-duplicate per
`settings.dup_similarity_threshold` (cosine similarity = 1 - cosine_distance,
since pgvector's `cosine_distance` returns 1 - cosine_similarity).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from agents.clients import EmbeddingsClient
from app.config import settings
from app.models import Note
from app.repositories.note import NoteRepository


async def embed_capture(body: str, *, embeddings: EmbeddingsClient) -> list[float]:
    """Embed a single capture body, returning its 1024-dim vector."""
    vectors = await embeddings.embed([body or ""])
    return vectors[0]


async def nearest_neighbors(session: AsyncSession, embedding: list[float], k: int = 5) -> list[Note]:
    """Return the k nearest existing notes to `embedding`, closest first."""
    repo = NoteRepository(session)
    return await repo.nearest(embedding, k=k)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_duplicate(embedding: list[float], neighbors: list[Note]) -> uuid.UUID | None:
    """Return the id of the top neighbor if it's a near-duplicate, else None.

    A neighbor is a near-duplicate when its cosine similarity to `embedding`
    is >= `settings.dup_similarity_threshold` (default 0.90, FR11).
    """
    if not neighbors:
        return None
    top = neighbors[0]
    if top.embedding is None:
        return None
    similarity = cosine_similarity(embedding, list(top.embedding))
    if similarity >= settings.dup_similarity_threshold:
        return top.id
    return None
