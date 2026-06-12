"""Vault writer (Epic 5 — Obsidian Vault Integration, Stories 5.1-5.4).

`VaultWriter.write_note(doc)` is the single point where Spore writes a
Markdown file (with YAML frontmatter, per FR16) into the Obsidian vault and
makes one atomic git commit (FR18). Epic 4's review actions (approve/
redirect) and Epic 3's confidence gate (direct-write / needs-review notes)
call this seam.

THE VAULT IS SACRED (CLAUDE.md rule 6): `GitVaultWriter` NEVER writes outside
its configured `base_path`. In dev, `base_path` is `vault/_sandbox/`
(settings.vault_path). Below-REVIEW_FLOOR captures never call this module —
that invariant is enforced by agents/gate.py + agents/triage.py, not here.

Implementation notes:
- Pure-python git via `dulwich` (no system `git` binary required — works in
  tests and the slim Docker image).
- `NoteDoc` / `RelatedRef` are plain dataclasses, decoupled from the ORM.
  Callers adapt `app.models.Note` -> `NoteDoc` via `app.vault_adapter.note_to_doc`.
- `NoOpVaultWriter` remains for explicit opt-out (settings.vault_path empty
  or "none"); it never touches the filesystem.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from dulwich import porcelain
from dulwich.repo import Repo

from app.config import DEFAULT_VAULT_PARA_MAP, settings

logger = logging.getLogger("spore")

NEEDS_REVIEW_TAG = "needs-review"
DEFAULT_PARA_FOLDER = "00_Inbox"

_BOT_AUTHOR = b"Spore Bot <bot@spore.local>"


# ── Plain-data types (decoupled from ORM) ──────────────────────────────────


@dataclass
class RelatedRef:
    """A related note, as far as the vault writer needs to know."""

    note_id: str
    title: str
    vault_path: str | None = None


@dataclass
class NoteDoc:
    """Everything `GitVaultWriter.write_note` needs to render a note."""

    note_id: str
    title: str
    type: str | None
    status: str
    source: str | None
    tags: list[str] = field(default_factory=list)
    domain: str | None = None
    created: datetime | None = None
    body: str = ""
    related: list[RelatedRef] = field(default_factory=list)


# ── Protocol + NoOp ──────────────────────────────────────────────────────


class VaultWriter(Protocol):
    async def write_note(self, doc: NoteDoc) -> str:
        """Persist `doc` to the vault; return its relative vault path."""
        ...


class NoOpVaultWriter:
    """Logs the write intent; performs no filesystem I/O."""

    async def write_note(self, doc: NoteDoc) -> str:
        path = f"{DEFAULT_PARA_FOLDER}/{slugify(doc.title)}.md"
        logger.info(
            "vault_write_noop",
            extra={"note_id": doc.note_id, "note_type": doc.type, "vault_path": path},
        )
        return path


# ── Helpers ────────────────────────────────────────────────────────────────


def slugify(title: str | None) -> str:
    """Turn a title into a filesystem-safe slug. Empty/None -> 'untitled'."""
    title = (title or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", title).strip("-")
    return slug or "untitled"


def para_folder_for(note_type: str | None) -> str:
    """Map a note `type` to its PARA folder (settings-overridable)."""
    para_map = settings.vault_para_map or DEFAULT_VAULT_PARA_MAP
    if note_type is None:
        return DEFAULT_PARA_FOLDER
    return para_map.get(note_type, DEFAULT_PARA_FOLDER)


# ── GitVaultWriter ───────────────────────────────────────────────────────


class GitVaultWriter:
    """Writes Markdown notes (FR16) with backlinks (FR17), PARA + MOC
    placement (FR19), into a dulwich-managed git repo, one commit per write
    (FR18, Story 5.3).
    """

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()

    # -- public API ---------------------------------------------------------

    async def write_note(self, doc: NoteDoc) -> str:
        self._ensure_repo()

        folder = para_folder_for(doc.type)
        rel_path = self._unique_path(folder, doc.title)
        abs_path = self._abs(rel_path)

        changed_paths: set[str] = set()

        # 1. Render and write this note's own file.
        content = self._render_note(doc)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
        changed_paths.add(rel_path)

        # 2. Bidirectional backlinks (FR17, Story 5.2): for each related note
        # that already has a file in the vault, append a Backlinks entry
        # pointing back to this note.
        for ref in doc.related:
            if not ref.vault_path:
                continue
            if self._append_backlink(ref.vault_path, doc.title):
                changed_paths.add(ref.vault_path)

        # 3. MOC (FR19, Story 5.4): ensure this note is listed in its
        # folder's _MOC.md.
        moc_path = self._ensure_moc_entry(folder, doc.title)
        if moc_path is not None:
            changed_paths.add(moc_path)

        # 4. One atomic commit for everything this write touched (FR18).
        self._commit(changed_paths, doc)

        return rel_path

    # -- repo setup -----------------------------------------------------------

    def _ensure_repo(self) -> None:
        self.base_path.mkdir(parents=True, exist_ok=True)
        git_dir = self.base_path / ".git"
        if not git_dir.exists():
            porcelain.init(str(self.base_path))

    def _abs(self, rel_path: str) -> Path:
        """Resolve `rel_path` under `base_path`, refusing any escape."""
        abs_path = (self.base_path / rel_path).resolve()
        if abs_path != self.base_path and self.base_path not in abs_path.parents:
            raise ValueError(f"refusing to write outside vault base_path: {rel_path}")
        return abs_path

    # -- path / slug handling --------------------------------------------------

    def _unique_path(self, folder: str, title: str) -> str:
        """`<folder>/<slug>.md`, deduped with -2, -3, ... on collision."""
        slug = slugify(title)
        candidate = f"{folder}/{slug}.md"
        if not self._abs(candidate).exists():
            return candidate

        n = 2
        while True:
            candidate = f"{folder}/{slug}-{n}.md"
            if not self._abs(candidate).exists():
                return candidate
            n += 1

    # -- rendering --------------------------------------------------------------

    def _render_note(self, doc: NoteDoc) -> str:
        created = (doc.created or datetime.utcnow()).isoformat()

        tags = list(doc.tags)
        if _status_needs_review(doc.status) and NEEDS_REVIEW_TAG not in tags:
            tags.append(NEEDS_REVIEW_TAG)

        links = [f"[[{ref.title}]]" for ref in doc.related]

        lines: list[str] = ["---"]
        lines.append(f"created: {created}")
        lines.append(f"source: {doc.source or ''}")
        lines.append(f"type: {doc.type or ''}")
        lines.append(f"status: {doc.status}")
        lines.append(_yaml_list("tags", tags))
        lines.append(_yaml_list("links", links))
        lines.append("---")
        lines.append("")
        lines.append(f"# {doc.title}")
        lines.append("")
        if doc.body:
            lines.append(doc.body.rstrip())
            lines.append("")

        return "\n".join(lines)

    # -- backlinks ----------------------------------------------------------

    def _append_backlink(self, related_rel_path: str, this_title: str) -> bool:
        """Append `- [[this_title]]` under `## Backlinks` in the related
        note's file. Returns True if the file changed."""
        abs_path = self._abs(related_rel_path)
        if not abs_path.exists():
            return False

        text = abs_path.read_text(encoding="utf-8")
        backlink_line = f"- [[{this_title}]]"

        if backlink_line in text:
            return False  # already linked, don't duplicate

        if "## Backlinks" in text:
            # Insert the new line right after the heading (and any existing
            # entries directly beneath it).
            new_text = _insert_after_heading(text, "## Backlinks", backlink_line)
        else:
            sep = "" if text.endswith("\n") else "\n"
            new_text = f"{text}{sep}\n## Backlinks\n{backlink_line}\n"

        abs_path.write_text(new_text, encoding="utf-8")
        return True

    # -- MOC ------------------------------------------------------------------

    def _ensure_moc_entry(self, folder: str, title: str) -> str | None:
        """Ensure `<folder>/_MOC.md` exists and lists `[[title]]`. Returns the
        relative MOC path if the file was created or changed, else None."""
        moc_rel = f"{folder}/_MOC.md"
        abs_path = self._abs(moc_rel)
        entry = f"- [[{title}]]"

        if not abs_path.exists():
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            content = f"# {folder} MOC\n\n{entry}\n"
            abs_path.write_text(content, encoding="utf-8")
            return moc_rel

        text = abs_path.read_text(encoding="utf-8")
        if entry in text:
            return None

        sep = "" if text.endswith("\n") else "\n"
        abs_path.write_text(f"{text}{sep}{entry}\n", encoding="utf-8")
        return moc_rel

    # -- git --------------------------------------------------------------------

    def _commit(self, changed_paths: set[str], doc: NoteDoc) -> None:
        repo = Repo(str(self.base_path))
        try:
            paths = sorted(changed_paths)
            porcelain.add(repo, [str(self._abs(p)) for p in paths])
            message = f"vault: add {doc.title} ({doc.type or 'note'})"
            porcelain.commit(
                repo,
                message=message.encode("utf-8"),
                author=_BOT_AUTHOR,
                committer=_BOT_AUTHOR,
            )
        finally:
            repo.close()


# ── module-level helpers ───────────────────────────────────────────────────


def _status_needs_review(status: str) -> bool:
    return status == NEEDS_REVIEW_TAG or "needs_review" in status or "needs-review" in status


def _yaml_list(key: str, values: list[str]) -> str:
    if not values:
        return f"{key}: []"
    items = "\n".join(f"  - {_yaml_scalar(v)}" for v in values)
    return f"{key}:\n{items}"


def _yaml_scalar(value: str) -> str:
    """Quote a YAML scalar if it contains characters that need escaping."""
    if re.search(r'[:\[\]{}#&*!|>\'"%@`,]', value) or value.strip() != value:
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _insert_after_heading(text: str, heading: str, new_line: str) -> str:
    """Insert `new_line` as the first item under `heading`'s existing list
    block (after the heading line and any immediately-following `- ` lines)."""
    lines = text.splitlines()
    idx = lines.index(heading)
    insert_at = idx + 1
    # Skip a single blank line right after the heading, if present.
    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    lines.insert(insert_at, new_line)
    result = "\n".join(lines)
    if text.endswith("\n"):
        result += "\n"
    return result


# ── factory ────────────────────────────────────────────────────────────────


def get_vault_writer() -> VaultWriter:
    """Factory for the configured vault writer.

    Returns `NoOpVaultWriter` only if `settings.vault_path` is empty or the
    literal string "none" (explicit opt-out); otherwise a `GitVaultWriter`
    rooted at `settings.vault_path`.
    """
    vault_path = (settings.vault_path or "").strip()
    if not vault_path or vault_path.lower() == "none":
        return NoOpVaultWriter()
    return GitVaultWriter(vault_path)
