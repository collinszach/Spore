"""Adapter: ORM `Note` -> `app.vault.NoteDoc` (Epic 5).

Decouples `GitVaultWriter` from SQLAlchemy. `note_to_doc` loads the titles
and vault paths of any `note_link`-related notes so the writer can render
`links:` frontmatter and write bidirectional backlinks (FR17).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note, NoteLink
from app.vault import NEEDS_REVIEW_TAG, NoteDoc, RelatedRef


async def note_to_doc(session: AsyncSession, note: Note, *, body: str = "") -> NoteDoc:
    """Build a `NoteDoc` for `note`, resolving related notes via `note_link`.

    `body` is the Markdown body to render under the `# Title` heading (the
    caller decides what that is — e.g. the source capture's text).
    """
    related: list[RelatedRef] = []

    stmt = select(NoteLink).where(NoteLink.src_id == note.id)
    result = await session.execute(stmt)
    links = list(result.scalars().all())

    for link in links:
        related_note = await session.get(Note, link.dst_id)
        if related_note is None:
            continue
        related.append(
            RelatedRef(
                note_id=str(related_note.id),
                title=related_note.title or str(related_note.id),
                vault_path=related_note.vault_path,
            )
        )

    tags = list(note.tags or [])
    status = "needs-review" if NEEDS_REVIEW_TAG in tags else "active"

    return NoteDoc(
        note_id=str(note.id),
        title=note.title or str(note.id),
        type=note.type,
        status=status,
        source="spore",
        tags=tags,
        domain=note.domain,
        created=note.created_at,
        body=body,
        related=related,
    )
