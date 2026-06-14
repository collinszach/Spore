"""APNs transport — JWT (ES256) auth + HTTP/2 push (Epic 8 delivery wiring).

Kept separate from `app.notify` so tests can inject a fake `ApnsTransport`
with no real network/HTTP2 stack. Two pieces:

- `ApnsTokenSigner`: signs/caches a provider JWT (kid=APNS_KEY_ID,
  iss=APNS_TEAM_ID, iat=now) per Apple's token-based auth scheme. APNs
  tokens are valid up to ~1h; we refresh a few minutes early.
- `ApnsTransport` (protocol) / `HttpxApnsTransport`: POSTs
  `https://{host}/3/device/{token}` with the bearer JWT, apns-topic,
  apns-push-type headers and an `{"aps": {...}}` payload. Uses httpx with
  `http2=True` (APNs requires HTTP/2).

`ApnsClient` ties the two together and is what `ApnsNotifier` (app.notify)
calls — `send_to_token(token, title, body, meta)`.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

import httpx
import jwt

logger = logging.getLogger("spore")

APNS_PROD_HOST = "api.push.apple.com"
APNS_SANDBOX_HOST = "api.sandbox.push.apple.com"

# Refresh the provider JWT a bit before Apple's ~1h expiry window.
_TOKEN_TTL_SECONDS = 50 * 60


class ApnsTokenSigner:
    """Signs and caches an APNs provider JWT (ES256) per Apple's token auth.

    `private_key` is the PEM contents of the .p8 key (read once by the
    caller — never logged/printed). `key_id` -> JWT header `kid`, `team_id`
    -> claim `iss`. `sign()` reuses the cached token until it's within
    `_TOKEN_TTL_SECONDS` of being stale.
    """

    def __init__(self, private_key: str, key_id: str, team_id: str):
        self.private_key = private_key
        self.key_id = key_id
        self.team_id = team_id
        self._cached_token: str | None = None
        self._cached_at: float = 0.0

    def sign(self, now: float | None = None) -> str:
        now = now if now is not None else time.time()
        if self._cached_token is not None and (now - self._cached_at) < _TOKEN_TTL_SECONDS:
            return self._cached_token

        token = jwt.encode(
            {"iss": self.team_id, "iat": int(now)},
            self.private_key,
            algorithm="ES256",
            headers={"kid": self.key_id},
        )
        self._cached_token = token
        self._cached_at = now
        return token


class ApnsTransport(Protocol):
    """HTTP/2 transport for a single APNs push. Implementations must not raise
    on a per-device delivery failure — return a result the caller can log."""

    async def post(self, host: str, device_token: str, headers: dict[str, str], json: dict) -> "ApnsResult":
        ...


class ApnsResult:
    """Outcome of one APNs push attempt."""

    def __init__(self, status_code: int, body: str = ""):
        self.status_code = status_code
        self.body = body

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class HttpxApnsTransport:
    """Real APNs transport — httpx client with HTTP/2 enabled."""

    def __init__(self, timeout: float = 10.0):
        self._client = httpx.AsyncClient(http2=True, timeout=timeout)

    async def post(self, host: str, device_token: str, headers: dict[str, str], json: dict) -> ApnsResult:
        url = f"https://{host}/3/device/{device_token}"
        response = await self._client.post(url, headers=headers, json=json)
        return ApnsResult(status_code=response.status_code, body=response.text)

    async def aclose(self) -> None:
        await self._client.aclose()


class ApnsClient:
    """Sends a single alert push to a device token via APNs.

    `transport` defaults to `HttpxApnsTransport` (real network); tests pass
    a fake. `host` is chosen from `use_sandbox`.
    """

    def __init__(
        self,
        signer: ApnsTokenSigner,
        topic: str,
        use_sandbox: bool = True,
        transport: ApnsTransport | None = None,
    ):
        self.signer = signer
        self.topic = topic
        self.host = APNS_SANDBOX_HOST if use_sandbox else APNS_PROD_HOST
        self.transport = transport or HttpxApnsTransport()

    async def send_alert(self, device_token: str, title: str, body: str, meta: dict | None = None) -> ApnsResult:
        jwt_token = self.signer.sign()
        headers = {
            "authorization": f"bearer {jwt_token}",
            "apns-topic": self.topic,
            "apns-push-type": "alert",
        }
        payload: dict = {"aps": {"alert": {"title": title, "body": body}}}
        if meta:
            payload.update({k: v for k, v in meta.items() if k != "aps"})

        result = await self.transport.post(self.host, device_token, headers, payload)
        if not result.ok:
            logger.warning(
                "apns_push_failed",
                extra={"device_token": device_token, "status_code": result.status_code, "body": result.body},
            )
        return result
