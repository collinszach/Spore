"""Tests for the Epic 6 skills engine (loader, Builder runtime, API).

Pure tests (loader, template/var substitution, sandbox safety) run with no
DB and no network — these are the ones the agent-engineer runs locally.
Builder/API tests that touch `note`, `skill_run`, `idea_event` need a real
Postgres test DB (DATABASE_URL) with 001_init.sql applied; they follow the
per-test, loop-local engine / dependency-override pattern from
tests/test_capture.py and are intended for the PM to run on remote.

All tests use FakeClaudeClient (agents.clients) — no live API keys.
"""

from __future__ import annotations

import os
import uuid

import pytest
import yaml
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agents.builder import _render, run_skill
from agents.clients import FakeClaudeClient
from agents.skills_registry import Skill, load_skills
from app.config import settings
from app.db import _to_async_dsn, get_database_url, get_session
from app.main import app
from app.models import IdeaEvent, Note, SkillRun
from app.vault import GitVaultWriter

TOKEN = os.environ.get("SPORE_CAPTURE_TOKEN", "dev-token")

REPO_ROOT_SKILLS_DIR = settings.skills_dir


# ── Loader (pure, tmp_path) ────────────────────────────────────────────────


def _write_skill_file(tmp_path, filename: str, data: dict) -> None:
    (tmp_path / filename).write_text(yaml.safe_dump(data), encoding="utf-8")


def test_load_skills_registers_two_files_with_no_code_change(tmp_path):
    _write_skill_file(
        tmp_path,
        "alpha.skill.yaml",
        {
            "name": "alpha",
            "trigger": {"manual": True},
            "prompt": "do alpha things",
            "output": {"path": "10_Notes/{{slug}}-alpha.md"},
        },
    )
    _write_skill_file(
        tmp_path,
        "beta.skill.yaml",
        {
            "name": "beta",
            "trigger": {"on_promote_to": "project", "input_types": ["project_idea"]},
            "prompt": "do beta things",
            "output": {"template": "templates/beta.md", "path": "20_Projects/{{slug}}/BETA.md"},
            "post_actions": [{"set_idea_state": "project"}],
        },
    )

    skills = load_skills(tmp_path)

    assert set(skills.keys()) == {"alpha", "beta"}
    assert isinstance(skills["alpha"], Skill)
    assert skills["alpha"].trigger.manual is True
    assert skills["beta"].trigger.on_promote_to == "project"
    assert skills["beta"].trigger.input_types == ["project_idea"]
    assert skills["beta"].output.template == "templates/beta.md"
    assert skills["beta"].output.path == "20_Projects/{{slug}}/BETA.md"
    assert skills["beta"].post_actions == [{"set_idea_state": "project"}]


def test_load_skills_malformed_file_raises_clearly(tmp_path):
    # Missing required `output` field.
    _write_skill_file(
        tmp_path,
        "broken.skill.yaml",
        {"name": "broken", "prompt": "no output here"},
    )

    with pytest.raises(ValueError) as exc_info:
        load_skills(tmp_path)

    assert "broken.skill.yaml" in str(exc_info.value)


def test_load_skills_invalid_yaml_raises_clearly(tmp_path):
    (tmp_path / "badyaml.skill.yaml").write_text("name: [unclosed", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_skills(tmp_path)

    assert "badyaml.skill.yaml" in str(exc_info.value)


def test_load_skills_empty_dir_returns_empty_dict(tmp_path):
    assert load_skills(tmp_path) == {}


def test_load_skills_missing_dir_returns_empty_dict(tmp_path):
    assert load_skills(tmp_path / "does-not-exist") == {}


def test_real_skills_dir_loads_expand_to_spec_and_starters():
    skills = load_skills(REPO_ROOT_SKILLS_DIR)

    expected = {
        "expand_to_spec",
        "literature_note",
        "decision_doc",
        "atomic_split",
        "merge_duplicates",
    }
    assert expected <= set(skills.keys())

    expand = skills["expand_to_spec"]
    assert expand.output.template == "templates/spec_scaffold.md"
    assert expand.output.path == "20_Projects/{{slug}}/SPEC.md"
    assert expand.trigger.on_promote_to == "project"
    assert expand.post_actions == [
        {"create_folder": "20_Projects/{{slug}}"},
        {"set_idea_state": "project"},
        {"notify": "telegram"},
    ]

    for name in expected:
        skill = skills[name]
        if skill.output.template:
            template_path = (REPO_ROOT_SKILLS_DIR_PATH := __import__("pathlib").Path(REPO_ROOT_SKILLS_DIR)) / skill.output.template
            assert template_path.exists(), f"{name} template missing: {template_path}"


# ── Template / var substitution (pure) ──────────────────────────────────────


def test_render_substitutes_known_vars():
    text = "# {{title}}\n\nslug={{slug}} date={{date}}\n\n{{content}}"
    variables = {
        "title": "My Idea",
        "slug": "my-idea",
        "date": "2026-06-12",
        "content": "the model output",
        "body": "",
        "domain": "",
    }

    rendered = _render(text, variables)

    assert "# My Idea" in rendered
    assert "slug=my-idea date=2026-06-12" in rendered
    assert "the model output" in rendered


def test_render_leaves_unknown_vars_untouched():
    text = "{{title}} {{not_a_real_var}}"
    rendered = _render(text, {"title": "Hello"})

    assert rendered == "Hello {{not_a_real_var}}"


# ── Builder + vault sandbox (pure tmp_path, no DB) ───────────────────────────


def _make_skill(**output_overrides) -> Skill:
    output = {"path": "10_Notes/{{slug}}-out.md"}
    output.update(output_overrides)
    return Skill.model_validate(
        {
            "name": "test_skill",
            "trigger": {"manual": True},
            "prompt": "Summarize this note.",
            "output": output,
            "post_actions": [],
        }
    )


def test_sandbox_writer_never_escapes_base(tmp_path):
    writer = GitVaultWriter(tmp_path)

    rel_path = "../../etc/passwd"
    with pytest.raises(ValueError):
        writer._abs(rel_path)


async def test_write_raw_creates_file_and_commit(tmp_path):
    from dulwich.repo import Repo

    writer = GitVaultWriter(tmp_path)

    rel_path = await writer.write_raw("10_Notes/out.md", "hello world", "skill: test write")

    assert rel_path == "10_Notes/out.md"
    abs_path = tmp_path / rel_path
    assert abs_path.exists()
    assert abs_path.read_text() == "hello world"

    repo = Repo(str(tmp_path))
    try:
        head = repo.head()
        commit = repo[head]
        assert commit.message.decode() == "skill: test write"
    finally:
        repo.close()


# ── Builder + DB (loop-local-engine pattern; PM runs on remote) ─────────────


@pytest.fixture
async def db_sessionmaker():
    engine = create_async_engine(_to_async_dsn(get_database_url()), future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def client(db_sessionmaker):
    from httpx import ASGITransport, AsyncClient

    async def _override_get_session():
        async with db_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
async def seeded_note(db_sessionmaker):
    """Create a project_idea note for the test, deleting it (and any
    skill_run / idea_event rows referencing it) afterwards."""
    note_id = uuid.uuid4()
    async with db_sessionmaker() as session:
        note = Note(
            id=note_id,
            title="Spore Skills Engine",
            type="project_idea",
            domain="spore",
            idea_state="seedling",
            tags=[],
        )
        session.add(note)
        await session.commit()

    yield note_id

    async with db_sessionmaker() as session:
        await session.execute(delete(SkillRun).where(SkillRun.note_id == note_id))
        await session.execute(delete(IdeaEvent).where(IdeaEvent.note_id == note_id))
        await session.execute(delete(Note).where(Note.id == note_id))
        await session.commit()


async def test_run_skill_writes_templated_output_and_skill_run_and_idea_event(
    db_sessionmaker, seeded_note, tmp_path
):
    writer = GitVaultWriter(tmp_path)
    claude = FakeClaudeClient(model="claude-sonnet-4-6")

    skill = Skill.model_validate(
        yaml.safe_load(
            (
                __import__("pathlib").Path(REPO_ROOT_SKILLS_DIR) / "expand_to_spec.skill.yaml"
            ).read_text()
        )
    )

    async with db_sessionmaker() as session:
        note = await session.get(Note, seeded_note)
        assert note is not None
        assert note.idea_state == "seedling"

        summary = await run_skill(session, skill, note, claude=claude, vault_writer=writer)
        await session.commit()

    assert summary["status"] == "ok"
    assert summary["output_path"] == "20_Projects/spore-skills-engine/SPEC.md"

    abs_path = tmp_path / summary["output_path"]
    assert abs_path.exists()
    content = abs_path.read_text()
    assert "# Spore Skills Engine — SPEC" in content
    assert "fake Builder output" in content  # from FakeClaudeClient builder mode

    async with db_sessionmaker() as session:
        # skill_run row logged.
        from sqlalchemy import select

        result = await session.execute(
            select(SkillRun).where(SkillRun.note_id == seeded_note, SkillRun.skill == "expand_to_spec")
        )
        runs = result.scalars().all()
        assert len(runs) == 1
        assert runs[0].status == "ok"
        assert runs[0].output_path == "20_Projects/spore-skills-engine/SPEC.md"
        assert runs[0].model == "claude-sonnet-4-6"

        # idea_state updated + idea_event logged (set_idea_state: project).
        note = await session.get(Note, seeded_note)
        assert note.idea_state == "project"

        result = await session.execute(
            select(IdeaEvent).where(IdeaEvent.note_id == seeded_note)
        )
        events = result.scalars().all()
        assert len(events) == 1
        assert events[0].from_state == "seedling"
        assert events[0].to_state == "project"
        assert events[0].reason == "skill"

    # create_folder post_action wrote a placeholder under the project folder.
    assert (tmp_path / "20_Projects" / "spore-skills-engine" / ".gitkeep").exists()


# ── API: POST /skills/{name}/run ─────────────────────────────────────────────


async def test_run_skill_api_unknown_skill_returns_404(client):
    response = await client.post(
        "/skills/does_not_exist/run",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"note_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404


async def test_run_skill_api_missing_token_returns_401(client, seeded_note):
    response = await client.post(
        "/skills/expand_to_spec/run",
        json={"note_id": str(seeded_note)},
    )

    assert response.status_code == 401


async def test_run_skill_api_happy_path_returns_200_and_output_path(
    client, seeded_note, tmp_path, monkeypatch
):
    from agents.clients import ClaudeClient, get_claude_client
    from app.routers import skills as skills_router
    from app.vault import GitVaultWriter, VaultWriter, get_vault_writer

    writer = GitVaultWriter(tmp_path)

    def _override_vault_writer() -> VaultWriter:
        return writer

    def _override_claude() -> ClaudeClient:
        return FakeClaudeClient(model="claude-sonnet-4-6")

    app.dependency_overrides[skills_router._get_vault_writer] = _override_vault_writer
    app.dependency_overrides[skills_router._get_builder_claude_client] = _override_claude

    try:
        response = await client.post(
            "/skills/expand_to_spec/run",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"note_id": str(seeded_note)},
        )
    finally:
        app.dependency_overrides.pop(skills_router._get_vault_writer, None)
        app.dependency_overrides.pop(skills_router._get_builder_claude_client, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["skill"] == "expand_to_spec"
    assert payload["data"]["status"] == "ok"
    assert payload["data"]["output_path"] == "20_Projects/spore-skills-engine/SPEC.md"
    assert (tmp_path / payload["data"]["output_path"]).exists()


async def test_run_skill_api_unknown_note_returns_404(client):
    response = await client.post(
        "/skills/expand_to_spec/run",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"note_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404
