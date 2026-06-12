"""Provider abstractions for the runtime triage pipeline (Epic 3).

Two clients are needed by the Sorter pipeline:

- An embeddings client: `embed(texts) -> list[list[float]]`, 1024-dim
  (ADR-002, voyage-3-lite / mxbai-embed-large). Real implementations call
  Voyage AI or a local Ollama instance via httpx; `FakeEmbeddingsClient` is a
  deterministic, hash-seeded stand-in used by default and always in tests.
- A Claude client wrapper for the Sorter: takes a system+user prompt, returns
  parsed JSON plus token usage. Real implementation uses the `anthropic` SDK
  against a cheap model (`settings.sorter_model`); `FakeClaudeClient` returns
  a canned, schema-valid triage JSON (with a small steering rule so tests can
  control type/confidence) used whenever `ANTHROPIC_API_KEY` is unset.

Factories (`get_embeddings_client` / `get_claude_client`) pick the
implementation: `get_embeddings_client` uses `settings.embeddings_provider`
("ollama" / "voyage" / "fake", default "fake"); `get_claude_client` uses the
real Anthropic client iff `ANTHROPIC_API_KEY` is set, else the fake. Tests
inject fakes explicitly and never hit the network.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024

VOYAGE_EMBEDDINGS_URL = "https://api.voyageai.com/v1/embeddings"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


# ── Embeddings ───────────────────────────────────────────────────────────


class EmbeddingsClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one 1024-dim embedding vector per input text."""
        ...


class VoyageEmbeddingsClient:
    """Real embeddings client: Voyage AI `voyage-3-lite` via httpx."""

    def __init__(self, api_key: str, model: str | None = None, timeout: float = 30.0):
        self.api_key = api_key
        self.model = model or settings.embedding_model
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                VOYAGE_EMBEDDINGS_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": texts, "model": self.model},
            )
            response.raise_for_status()
            payload = response.json()
        return [item["embedding"] for item in payload["data"]]


class OllamaEmbeddingsClient:
    """Real embeddings client: local Ollama `/api/embeddings` via httpx.

    Ollama's stable embeddings endpoint takes a single `prompt` per request
    (no batch input), so `embed()` issues one POST per text and collects the
    results in order. Each returned vector is checked against `EMBEDDING_DIM`
    (1024, matching the `VECTOR(1024)` DB column) — a mismatched dimension
    raises rather than silently returning a wrong-shape vector.
    """

    def __init__(self, base_url: str, model: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.base_url}/api/embeddings"
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for text in texts:
                response = await client.post(url, json={"model": self.model, "prompt": text})
                if response.status_code != 200:
                    raise RuntimeError(
                        f"Ollama embeddings request failed: HTTP {response.status_code} "
                        f"{response.text!r}"
                    )
                payload = response.json()
                embedding = payload.get("embedding")
                if embedding is None:
                    raise RuntimeError(f"Ollama embeddings response missing 'embedding': {payload!r}")
                if len(embedding) != EMBEDDING_DIM:
                    raise RuntimeError(
                        f"Ollama embeddings response has dim {len(embedding)}, "
                        f"expected {EMBEDDING_DIM} (model={self.model!r})"
                    )
                vectors.append(embedding)
        return vectors


class FakeEmbeddingsClient:
    """Deterministic embeddings client for tests / no-key local dev.

    Hashes each text to seed a PRNG, then draws a 1024-dim vector and
    normalizes it to unit length. Identical input text always yields an
    identical vector, so dedup/kNN logic can be exercised without a network
    call or live Voyage key.
    """

    dim = EMBEDDING_DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big")
        rng = random.Random(seed)
        vec = [rng.gauss(0.0, 1.0) for _ in range(self.dim)]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


# ── Claude (Sorter) ──────────────────────────────────────────────────────


@dataclass
class ClaudeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class ClaudeResponse:
    """Result of a Sorter call: raw text plus parsed JSON (if parseable)."""

    text: str
    json: dict | None
    usage: ClaudeUsage
    model: str


class ClaudeClient(Protocol):
    model: str

    async def complete(self, system: str, user: str) -> ClaudeResponse:
        """Send a system+user prompt, return parsed JSON + token usage."""
        ...


class AnthropicClaudeClient:
    """Real Claude client using the `anthropic` SDK against a cheap model."""

    def __init__(self, api_key: str, model: str | None = None, max_tokens: int = 1024):
        from anthropic import AsyncAnthropic

        self.model = model or settings.sorter_model
        self.max_tokens = max_tokens
        self._client = AsyncAnthropic(api_key=api_key)

    async def complete(self, system: str, user: str) -> ClaudeResponse:
        message = await self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text_parts = [block.text for block in message.content if getattr(block, "type", None) == "text"]
        text = "".join(text_parts)
        parsed = _try_parse_json(text)
        usage = ClaudeUsage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )
        return ClaudeResponse(text=text, json=parsed, usage=usage, model=self.model)


class FakeClaudeClient:
    """Canned, schema-valid Sorter response for tests / no-key local dev.

    Returns a `TriageResult`-shaped JSON document. A small steering rule lets
    tests control the output without a live model: if the CAPTURE BODY
    contains "TODO" (case-insensitive), the response is classified as a task
    with high confidence; otherwise it's a fleeting note with a mid-high
    confidence. `related_ids` / `duplicate_of` are left empty — the pipeline
    fills those in from the kNN + dedup step before validation.

    The rule inspects only the capture body, not the whole prompt: neighbor
    notes are listed in the prompt with their titles, and a neighbor titled
    "TODO ..." must not flip an unrelated capture to a task.
    """

    model = "fake-sorter"

    def __init__(self, usage: ClaudeUsage | None = None):
        self.usage = usage or ClaudeUsage(input_tokens=0, output_tokens=0)

    @staticmethod
    def _capture_body(user: str) -> str:
        """Extract just the 'Capture body:' section of the Sorter prompt."""
        marker = "Capture body:\n"
        start = user.find(marker)
        if start == -1:
            return user
        start += len(marker)
        end = user.find("\n\nCandidate related notes", start)
        return user[start:] if end == -1 else user[start:end]

    async def complete(self, system: str, user: str) -> ClaudeResponse:
        if "todo" in self._capture_body(user).lower():
            payload = {
                "type": "task",
                "tags": ["task"],
                "domain": None,
                "urgency": "soon",
                "actionability": "actionable",
                "routing_confidence": 0.9,
                "related_ids": [],
                "duplicate_of": None,
            }
        else:
            payload = {
                "type": "fleeting",
                "tags": ["fleeting"],
                "domain": None,
                "urgency": None,
                "actionability": "none",
                "routing_confidence": 0.85,
                "related_ids": [],
                "duplicate_of": None,
            }
        text = json.dumps(payload)
        return ClaudeResponse(text=text, json=payload, usage=self.usage, model=self.model)


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json_candidate(text: str) -> str:
    """Best-effort extraction of a JSON object from model output.

    Real models sometimes wrap their JSON in ```json ... ``` fences or add
    surrounding prose. This strips a fenced block if present, then falls
    back to the first balanced `{...}` object in the text. If neither is
    found, returns the input unchanged (so `json.loads` can raise its own
    error).
    """
    stripped = text.strip()

    fence_match = _CODE_FENCE_RE.search(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    # Find the first balanced {...} object, accounting for nested braces and
    # braces inside string literals.
    start = stripped.find("{")
    if start == -1:
        return stripped

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]

    return stripped


def _try_parse_json(text: str) -> dict | None:
    candidate = _extract_json_candidate(text)
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        return None


# ── Factories ────────────────────────────────────────────────────────────


def get_embeddings_client() -> EmbeddingsClient:
    """Select the embeddings client per `EMBEDDINGS_PROVIDER`.

    - "ollama": local Ollama embeddings (free). Falls back to the fake
      client (with a warning) if `OLLAMA_URL` is unset/empty.
    - "voyage": real Voyage AI client (requires `VOYAGE_API_KEY`).
    - anything else (including "fake" / unset): deterministic fake client.
    """
    provider = settings.embeddings_provider.lower()

    if provider == "ollama":
        if not settings.ollama_url:
            logger.warning(
                "EMBEDDINGS_PROVIDER=ollama but OLLAMA_URL is empty; falling back to "
                "FakeEmbeddingsClient"
            )
            return FakeEmbeddingsClient()
        return OllamaEmbeddingsClient(settings.ollama_url, settings.embedding_model)

    if provider == "voyage":
        if not settings.voyage_api_key:
            logger.warning(
                "EMBEDDINGS_PROVIDER=voyage but VOYAGE_API_KEY is empty; falling back to "
                "FakeEmbeddingsClient"
            )
            return FakeEmbeddingsClient()
        return VoyageEmbeddingsClient(api_key=settings.voyage_api_key)

    return FakeEmbeddingsClient()


def get_claude_client() -> ClaudeClient:
    """Real Anthropic client iff ANTHROPIC_API_KEY is set, else the fake."""
    if settings.anthropic_api_key:
        return AnthropicClaudeClient(api_key=settings.anthropic_api_key)
    return FakeClaudeClient()
