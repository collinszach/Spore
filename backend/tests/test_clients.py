"""Tests for `agents.clients` — embeddings/Claude client implementations and
factory selection (Epic 3 hardening: real Ollama embeddings + real Claude).

All tests are pure / no-network: httpx and the `anthropic` SDK calls are
monkeypatched or stubbed.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import httpx
import pytest

from agents.clients import (
    EMBEDDING_DIM,
    AnthropicClaudeClient,
    ClaudeUsage,
    FakeClaudeClient,
    FakeEmbeddingsClient,
    OllamaEmbeddingsClient,
    _try_parse_json,
    get_embeddings_client,
)
from app.config import settings


# ── OllamaEmbeddingsClient ──────────────────────────────────────────────


def _make_ollama_transport(handler):
    """Build an httpx.AsyncClient transport from a sync handler(request)."""

    async def _handler(request: httpx.Request) -> httpx.Response:
        return handler(request)

    return httpx.MockTransport(_handler)


@pytest.fixture
def fake_embedding() -> list[float]:
    return [0.001 * i for i in range(EMBEDDING_DIM)]


async def test_ollama_embed_returns_vectors_in_order(monkeypatch, fake_embedding):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        payload = _json.loads(request.content)
        calls.append(payload["prompt"])
        return httpx.Response(200, json={"embedding": fake_embedding})

    transport = _make_ollama_transport(handler)

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _PatchedAsyncClient)

    client = OllamaEmbeddingsClient(base_url="http://ollama:11434", model="mxbai-embed-large")
    result = await client.embed(["a", "b"])

    assert calls == ["a", "b"]
    assert len(result) == 2
    assert all(len(vec) == EMBEDDING_DIM for vec in result)
    assert result[0] == fake_embedding
    assert result[1] == fake_embedding


async def test_ollama_embed_raises_on_wrong_dim(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    transport = _make_ollama_transport(handler)

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _PatchedAsyncClient)

    client = OllamaEmbeddingsClient(base_url="http://ollama:11434", model="mxbai-embed-large")

    with pytest.raises(RuntimeError, match="dim"):
        await client.embed(["a"])


async def test_ollama_embed_raises_on_non_200(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    transport = _make_ollama_transport(handler)

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _PatchedAsyncClient)

    client = OllamaEmbeddingsClient(base_url="http://ollama:11434", model="mxbai-embed-large")

    with pytest.raises(RuntimeError, match="500"):
        await client.embed(["a"])


# ── Factory selection ───────────────────────────────────────────────────


def test_factory_defaults_to_fake(monkeypatch):
    monkeypatch.setattr(settings, "embeddings_provider", "fake")
    assert isinstance(get_embeddings_client(), FakeEmbeddingsClient)


def test_factory_unset_provider_is_fake(monkeypatch):
    monkeypatch.setattr(settings, "embeddings_provider", "")
    assert isinstance(get_embeddings_client(), FakeEmbeddingsClient)


def test_factory_ollama_provider_returns_ollama_client(monkeypatch):
    monkeypatch.setattr(settings, "embeddings_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_url", "http://ollama:11434")
    monkeypatch.setattr(settings, "embedding_model", "mxbai-embed-large")

    client = get_embeddings_client()

    assert isinstance(client, OllamaEmbeddingsClient)
    assert client.base_url == "http://ollama:11434"
    assert client.model == "mxbai-embed-large"


def test_factory_ollama_provider_with_empty_url_falls_back_to_fake(monkeypatch):
    monkeypatch.setattr(settings, "embeddings_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_url", "")

    assert isinstance(get_embeddings_client(), FakeEmbeddingsClient)


def test_factory_voyage_provider_without_key_falls_back_to_fake(monkeypatch):
    monkeypatch.setattr(settings, "embeddings_provider", "voyage")
    monkeypatch.setattr(settings, "voyage_api_key", "")

    assert isinstance(get_embeddings_client(), FakeEmbeddingsClient)


# ── AnthropicClaudeClient JSON extraction ───────────────────────────────


@dataclass
class _StubTextBlock:
    text: str
    type: str = "text"


def _stub_message(text: str, input_tokens: int = 100, output_tokens: int = 50):
    return SimpleNamespace(
        content=[_StubTextBlock(text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class _StubMessages:
    def __init__(self, message):
        self._message = message

    async def create(self, **kwargs):
        return self._message


class _StubAnthropicClient:
    def __init__(self, message):
        self.messages = _StubMessages(message)


def _make_claude_client(message) -> AnthropicClaudeClient:
    client = AnthropicClaudeClient(api_key="sk-test", model="claude-haiku-4-5-20251001")
    client._client = _StubAnthropicClient(message)
    return client


VALID_PAYLOAD = {
    "type": "fleeting",
    "tags": ["note"],
    "domain": None,
    "urgency": None,
    "actionability": "none",
    "routing_confidence": 0.7,
    "related_ids": [],
    "duplicate_of": None,
}


async def test_anthropic_client_parses_fenced_json():
    import json as _json

    fenced = "```json\n" + _json.dumps(VALID_PAYLOAD) + "\n```"
    message = _stub_message(fenced, input_tokens=120, output_tokens=40)
    client = _make_claude_client(message)

    response = await client.complete("system prompt", "user prompt")

    assert response.json == VALID_PAYLOAD
    assert response.usage == ClaudeUsage(input_tokens=120, output_tokens=40)
    assert response.model == "claude-haiku-4-5-20251001"


async def test_anthropic_client_parses_json_with_surrounding_prose():
    import json as _json

    text = "Sure thing! Here is the classification:\n" + _json.dumps(VALID_PAYLOAD) + "\nLet me know if you need anything else."
    message = _stub_message(text)
    client = _make_claude_client(message)

    response = await client.complete("system prompt", "user prompt")

    assert response.json == VALID_PAYLOAD


async def test_anthropic_client_returns_none_json_for_garbage():
    message = _stub_message("this is not json at all, sorry!")
    client = _make_claude_client(message)

    response = await client.complete("system prompt", "user prompt")

    assert response.json is None
    assert response.text == "this is not json at all, sorry!"


def test_try_parse_json_strips_fences_and_prose():
    import json as _json

    fenced = "```json\n" + _json.dumps(VALID_PAYLOAD) + "\n```"
    assert _try_parse_json(fenced) == VALID_PAYLOAD

    prose = "Here you go:\n" + _json.dumps(VALID_PAYLOAD) + "\nthanks!"
    assert _try_parse_json(prose) == VALID_PAYLOAD

    assert _try_parse_json("not json") is None


# ── FakeClaudeClient capture-body rule (unchanged contract) ─────────────


async def test_fake_claude_client_capture_body_rule_still_works():
    fake = FakeClaudeClient()

    user_with_todo = "Capture body:\nTODO buy milk\n\nCandidate related notes (from kNN search):\n(none)\n\nReturn the JSON object now."
    response = await fake.complete("system", user_with_todo)
    assert response.json["type"] == "task"

    user_without_todo = "Capture body:\njust a fleeting thought\n\nCandidate related notes (from kNN search):\n(none)\n\nReturn the JSON object now."
    response = await fake.complete("system", user_without_todo)
    assert response.json["type"] == "fleeting"
