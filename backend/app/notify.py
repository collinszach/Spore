"""Delivery seam for Epic 8 (FR30/FR32/FR33) — push notifications.

`Notifier.send(channel, title, body, meta)` is the single chokepoint for
outbound delivery (APNs/Telegram/ntfy). No tokens exist yet, so
`get_notifier()` always returns `NoOpNotifier`, which just logs the intent.
When APNs/Telegram/ntfy credentials land, add real implementations here and
switch the factory — reminder-fire and the Curator digests already call this
seam and need no changes.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("spore")


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


def get_notifier() -> Notifier:
    """Factory — returns NoOpNotifier until APNs/Telegram/ntfy tokens exist."""
    return NoOpNotifier()
