"""Vault-write seam (Epic 5 placeholder).

`VaultWriter.write_note(note)` is the single point where Spore would write a
Markdown file (with YAML frontmatter, per FR16) into the Obsidian vault.
Epic 4's review actions (approve/redirect) call this seam so the "trigger
vault writes on approve" hooks already exist — Epic 5 fills in the real
implementation.

`NoOpVaultWriter` only logs intent; it NEVER touches the filesystem. The
vault is sacred (CLAUDE.md rule 6) — nothing under vault/ is written by this
module today.
"""

from __future__ import annotations

import logging
from typing import Protocol

from app.models import Note

logger = logging.getLogger("spore")


class VaultWriter(Protocol):
    async def write_note(self, note: Note) -> None:
        """Persist `note` to the vault as a Markdown file. No-op for now."""
        ...


class NoOpVaultWriter:
    """Logs the write intent; performs no filesystem I/O (Epic 5 seam)."""

    async def write_note(self, note: Note) -> None:
        logger.info(
            "vault_write_noop",
            extra={
                "note_id": str(note.id),
                "note_type": note.type,
                "vault_path": note.vault_path,
            },
        )


def get_vault_writer() -> VaultWriter:
    """Factory for the configured vault writer. Always NoOp until Epic 5."""
    return NoOpVaultWriter()
