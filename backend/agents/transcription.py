"""Transcription provider abstraction for voice captures (Story 2.6, ADR-001).

Mirrors the embeddings/Claude provider pattern in `agents/clients.py`:

- `TranscriptionClient` protocol: `transcribe(audio_bytes, filename) -> str`.
- `WhisperTranscriptionClient`: real implementation, posts multipart form data
  to a local Whisper ASR service (`{base_url}/asr?task=transcribe&output=txt`,
  field name `audio_file`) and returns the plain-text transcript.
- `FakeTranscriptionClient`: deterministic canned transcript, used in tests
  and whenever `TRANSCRIPTION_PROVIDER` is not "whisper" (no network call).

`get_transcription_client()` selects the implementation per
`settings.transcription_provider`.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TranscriptionClient(Protocol):
    async def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        """Transcribe `audio_bytes` (named `filename` for content-type hints) to text."""
        ...


class WhisperTranscriptionClient:
    """Real transcription client: local Whisper ASR service via httpx.

    POSTs multipart/form-data to `{base_url}/asr?task=transcribe&output=txt`
    with the audio bytes under the `audio_file` field. The service returns
    the transcript as plain text (HTTP 200, no auth).
    """

    def __init__(self, base_url: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        url = f"{self.base_url}/asr"
        params = {"task": "transcribe", "output": "txt"}
        files = {"audio_file": (filename, audio_bytes)}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, params=params, files=files)
            if response.status_code != 200:
                raise RuntimeError(
                    f"Whisper transcription request failed: HTTP {response.status_code} "
                    f"{response.text!r}"
                )
            return response.text.strip()


class FakeTranscriptionClient:
    """Deterministic canned transcript for tests / no-whisper local dev.

    Never makes a network call; always returns the same text for a given
    filename so tests can assert on the result.
    """

    async def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        return f"[transcript of {filename}]"


def get_transcription_client() -> TranscriptionClient:
    """Select the transcription client per `TRANSCRIPTION_PROVIDER`.

    - "whisper": real local Whisper ASR client (`settings.whisper_url`).
    - anything else (including "fake" / unset): deterministic fake client.
    """
    if settings.transcription_provider.lower() == "whisper":
        return WhisperTranscriptionClient(settings.whisper_url)
    return FakeTranscriptionClient()
