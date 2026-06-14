"""Delivery seam for Epic 8 (FR30/FR32/FR33) — push notifications.

`Notifier.send(channel, title, body, meta)` is the single chokepoint for
outbound delivery (APNs/Telegram/ntfy). `get_notifier()` returns
`NoOpNotifier` (logs intent only) unless APNs is configured
(`APNS_ENABLED=true`, `APNS_TEAM_ID` set, and the .p8 key file exists), in
which case it returns `ApnsNotifier`. reminder-fire and the Curator digests
already call this seam via `notifier.send(...)` and need no changes —
`ApnsNotifier` fetches device tokens itself via `token_provider`.

Session wiring: `ApnsNotifier` has no DB session of its own. Callers (e.g.
`app.routers.internal._get_notifier`) construct it with a `token_provider`
callable — typically `lambda: DeviceRepository(session).list_tokens()` bound
to the request's session — so `send()` can fan a push out to every
registered device without a global session.
"""

from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable, Protocol

from app.apns import ApnsClient, ApnsTokenSigner
from app.config import settings

logger = logging.getLogger("spore")

TokenProvider = Callable[[], Awaitable[list[str]]]


class Notifier(Protocol):
    async def send(self, channel: str, title: str, body: str, meta: dict | None = None) -> None:
        """Send a notification on `channel` (e.g. 'apns', 'digest-daily')."""
        ...


class NoOpNotifier:
    """Logs delivery intent without sending anything (no tokens configured)."""

    async def send(self, channel: str, title: str, body: str, meta: dict | None = None) -> None:
        logger.info(
            "notify_noop",
            extra={"channel": channel, "title": title, "body": body, "meta": meta or {}},
        )


class ApnsNotifier:
    """Sends a real APNs push to every registered device token.

    `token_provider` is an async callable returning the list of APNs device
    tokens to push to (see module docstring for the session-bound wiring).
    A failed push to one token is logged and does not abort the others.
    """

    def __init__(self, apns_client: ApnsClient, token_provider: TokenProvider):
        self.apns_client = apns_client
        self.token_provider = token_provider

    async def send(self, channel: str, title: str, body: str, meta: dict | None = None) -> None:
        tokens = await self.token_provider()
        if not tokens:
            logger.info("apns_send_no_devices", extra={"channel": channel, "title": title})
            return

        for token in tokens:
            try:
                await self.apns_client.send_alert(token, title, body, meta)
            except Exception:
                logger.exception("apns_send_error", extra={"channel": channel, "device_token": token})


def get_notifier(token_provider: TokenProvider | None = None) -> Notifier:
    """Factory — returns ApnsNotifier when APNs is configured, else NoOpNotifier.

    APNs is "configured" when `APNS_ENABLED=true`, `APNS_TEAM_ID` is set, and
    the .p8 key file at `APNS_KEY_PATH` exists. `token_provider` is required
    in that case (callers without one fall back to NoOpNotifier).
    """
    if (
        settings.apns_enabled
        and settings.apns_team_id
        and os.path.exists(settings.apns_key_path)
        and token_provider is not None
    ):
        with open(settings.apns_key_path, "r") as f:
            private_key = f.read()

        signer = ApnsTokenSigner(
            private_key=private_key,
            key_id=settings.apns_key_id,
            team_id=settings.apns_team_id,
        )
        apns_client = ApnsClient(signer, topic=settings.apns_topic, use_sandbox=settings.apns_use_sandbox)
        return ApnsNotifier(apns_client, token_provider)

    return NoOpNotifier()
