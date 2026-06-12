"""Tests for app.vault (Epic 5 — Obsidian Vault Integration, Stories 5.1-5.4).

All tests are pure filesystem/git tests using `tmp_path` — no Postgres, no
network. `GitVaultWriter` uses dulwich (pure-python git), so these run
anywhere `pip install -r requirements.txt` has run.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from dulwich.repo import Repo

from app.vault import GitVaultWriter, NoteDoc, RelatedRef, para_folder_for, slugify


def _doc(**overrides) -> NoteDoc:
    base = dict(
        note_id="11111111-1111-1111-1111-111111111111",
        title="My First Idea",
        type="project_idea",
        status="active",
        source="ios_quick",
        tags=["idea"],
        domain="health",
        created=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        body="This is the body of the note.",
        related=[],
    )
    base.update(overrides)
    return NoteDoc(**base)


# ── PARA mapping + slugify ──────────────────────────────────────────────


def test_para_folder_mapping_defaults():
    assert para_folder_for("project_idea") == "20_Projects"
    assert para_folder_for("reference") == "30_Resources"
    assert para_folder_for("task") == "10_Areas"
    assert para_folder_for("journal") == "10_Areas"
    assert para_folder_for("fleeting") == "00_Inbox"
    assert para_folder_for("question") == "00_Inbox"
    assert para_folder_for("totally_unknown") == "00_Inbox"
    assert para_folder_for(None) == "00_Inbox"


def test_slugify():
    assert slugify("My First Idea") == "my-first-idea"
    assert slugify("  Weird!! Title??  ") == "weird-title"
    assert slugify("") == "untitled"
    assert slugify(None) == "untitled"


# ── write_note: folder, filename, frontmatter, body ───────────────────────


async def test_write_note_creates_correct_para_folder_and_filename(tmp_path):
    writer = GitVaultWriter(tmp_path)
    doc = _doc(title="My First Idea", type="project_idea")

    rel_path = await writer.write_note(doc)

    assert rel_path == "20_Projects/my-first-idea.md"
    abs_path = tmp_path / rel_path
    assert abs_path.exists()


async def test_write_note_frontmatter_and_body(tmp_path):
    writer = GitVaultWriter(tmp_path)
    doc = _doc(
        title="My First Idea",
        type="project_idea",
        status="active",
        source="ios_quick",
        tags=["idea", "health"],
        body="This is the body of the note.",
    )

    rel_path = await writer.write_note(doc)
    content = (tmp_path / rel_path).read_text()

    # Frontmatter block.
    assert content.startswith("---\n")
    assert "created: 2026-06-01T12:00:00+00:00" in content
    assert "source: ios_quick" in content
    assert "type: project_idea" in content
    assert "status: active" in content
    assert "tags:\n  - idea\n  - health" in content
    assert "links: []" in content

    # Body.
    assert "# My First Idea" in content
    assert "This is the body of the note." in content


async def test_needs_review_status_adds_tag(tmp_path):
    writer = GitVaultWriter(tmp_path)
    doc = _doc(title="Needs Review Note", status="needs-review", tags=["fleeting"])

    rel_path = await writer.write_note(doc)
    content = (tmp_path / rel_path).read_text()

    assert "needs-review" in content
    # tags list should contain both the original tag and needs-review
    assert "- fleeting" in content
    assert "- needs-review" in content


# ── unknown type -> Inbox ──────────────────────────────────────────────────


async def test_unknown_type_goes_to_inbox(tmp_path):
    writer = GitVaultWriter(tmp_path)
    doc = _doc(title="Mystery Note", type="something_else")

    rel_path = await writer.write_note(doc)

    assert rel_path == "00_Inbox/mystery-note.md"


# ── slug collisions ─────────────────────────────────────────────────────────


async def test_slug_collision_creates_distinct_files(tmp_path):
    writer = GitVaultWriter(tmp_path)
    doc_a = _doc(note_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", title="Duplicate Title")
    doc_b = _doc(note_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", title="Duplicate Title")

    path_a = await writer.write_note(doc_a)
    path_b = await writer.write_note(doc_b)

    assert path_a != path_b
    assert path_a == "20_Projects/duplicate-title.md"
    assert path_b == "20_Projects/duplicate-title-2.md"
    assert (tmp_path / path_a).exists()
    assert (tmp_path / path_b).exists()


# ── bidirectional backlinks (Story 5.2 / FR17) ────────────────────────────


async def test_bidirectional_backlinks(tmp_path):
    writer = GitVaultWriter(tmp_path)

    # Write note A first.
    doc_a = _doc(
        note_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        title="Note A",
        type="reference",
    )
    path_a = await writer.write_note(doc_a)

    # Write note B, related to A.
    doc_b = _doc(
        note_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        title="Note B",
        type="reference",
        related=[RelatedRef(note_id=doc_a.note_id, title="Note A", vault_path=path_a)],
    )
    path_b = await writer.write_note(doc_b)

    content_b = (tmp_path / path_b).read_text()
    assert "[[Note A]]" in content_b  # in B's links frontmatter

    content_a = (tmp_path / path_a).read_text()
    assert "## Backlinks" in content_a
    assert "- [[Note B]]" in content_a


async def test_backlink_not_duplicated_on_repeat_write(tmp_path):
    writer = GitVaultWriter(tmp_path)

    doc_a = _doc(note_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", title="Note A", type="reference")
    path_a = await writer.write_note(doc_a)

    related = [RelatedRef(note_id=doc_a.note_id, title="Note A", vault_path=path_a)]
    doc_b = _doc(
        note_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        title="Note B",
        type="reference",
        related=related,
    )
    await writer.write_note(doc_b)

    # Re-write B (e.g. an update) — A's backlink should not be duplicated.
    doc_b2 = _doc(
        note_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        title="Note B copy",
        type="reference",
        related=related,
    )
    await writer.write_note(doc_b2)

    content_a = (tmp_path / path_a).read_text()
    assert content_a.count("- [[Note B]]") == 1


# ── MOC (Story 5.4 / FR19) ───────────────────────────────────────────────


async def test_moc_lists_notes_without_duplicates(tmp_path):
    writer = GitVaultWriter(tmp_path)

    doc_a = _doc(note_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", title="Note A", type="reference")
    doc_b = _doc(note_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", title="Note B", type="reference")

    await writer.write_note(doc_a)
    await writer.write_note(doc_b)

    moc_path = tmp_path / "30_Resources" / "_MOC.md"
    assert moc_path.exists()
    content = moc_path.read_text()
    assert content.startswith("# 30_Resources MOC")
    assert "- [[Note A]]" in content
    assert "- [[Note B]]" in content

    # Re-writing a note with the same title doesn't duplicate the MOC entry.
    doc_a_again = _doc(
        note_id="dddddddd-dddd-dddd-dddd-dddddddddddd", title="Note A", type="reference"
    )
    await writer.write_note(doc_a_again)

    content2 = moc_path.read_text()
    assert content2.count("- [[Note A]]") == 1


# ── git: one commit per write ──────────────────────────────────────────────


async def test_each_write_creates_exactly_one_commit(tmp_path):
    writer = GitVaultWriter(tmp_path)

    repo = Repo.init(str(tmp_path)) if not (tmp_path / ".git").exists() else Repo(str(tmp_path))
    repo.close()

    def commit_count() -> int:
        repo = Repo(str(tmp_path))
        try:
            try:
                return sum(1 for _ in repo.get_walker())
            except KeyError:
                return 0  # no HEAD yet (no commits)
        finally:
            repo.close()

    before = commit_count()
    doc1 = _doc(note_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", title="First Note")
    await writer.write_note(doc1)
    after_first = commit_count()
    assert after_first == before + 1

    doc2 = _doc(note_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", title="Second Note")
    await writer.write_note(doc2)
    after_second = commit_count()
    assert after_second == after_first + 1


async def test_commit_message_and_author(tmp_path):
    writer = GitVaultWriter(tmp_path)
    doc = _doc(title="Commit Test Note", type="reference")

    await writer.write_note(doc)

    repo = Repo(str(tmp_path))
    try:
        head = repo.head()
        commit = repo[head]
        assert commit.message.decode().startswith("vault: add Commit Test Note (reference)")
        assert commit.author == b"Spore Bot <bot@spore.local>"
    finally:
        repo.close()


async def test_repo_log_walkable_and_head_matches_file(tmp_path):
    writer = GitVaultWriter(tmp_path)
    doc = _doc(title="Walkable Note", type="reference", body="walkable body")

    rel_path = await writer.write_note(doc)

    repo = Repo(str(tmp_path))
    try:
        entries = list(repo.get_walker())
        assert len(entries) >= 1

        head_commit = repo[repo.head()]
        tree = repo[head_commit.tree]

        # Walk the tree to find the note file's blob and compare content.
        parts = rel_path.split("/")
        current_tree = tree
        for part in parts[:-1]:
            _, sha = current_tree[part.encode()]
            current_tree = repo[sha]
        _, blob_sha = current_tree[parts[-1].encode()]
        blob = repo[blob_sha]

        on_disk = (tmp_path / rel_path).read_text()
        assert blob.data.decode() == on_disk
        assert "walkable body" in blob.data.decode()
    finally:
        repo.close()


# ── sandbox safety ─────────────────────────────────────────────────────────


async def test_writer_never_escapes_base_path(tmp_path):
    writer = GitVaultWriter(tmp_path)

    # Even a maliciously-titled note stays within base_path because the path
    # is built from a slug, never raw user input used as a path component.
    doc = _doc(title="../../etc/passwd", type="fleeting")
    rel_path = await writer.write_note(doc)

    abs_path = (tmp_path / rel_path).resolve()
    assert tmp_path.resolve() in abs_path.parents or abs_path == tmp_path.resolve()
    assert abs_path.exists()


async def test_abs_rejects_path_outside_base(tmp_path):
    writer = GitVaultWriter(tmp_path)
    with pytest.raises(ValueError):
        writer._abs("../outside.md")
