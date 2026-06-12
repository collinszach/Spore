"""Declarative skill loader (Epic 6, Story 6.1 — SPEC.md §4).

Each skill is a `*.skill.yaml` file under `settings.skills_dir`. Dropping a
new file into that directory registers the skill with **no code change**
(Story 6.1 AC) — `load_skills` just globs the directory and parses each file
into a `Skill` model.

Schema (SPEC.md §4):

    name: expand_to_spec
    trigger:
      on_promote_to: project        # or: manual, on_capture, on_schedule
      input_types: [project_idea]
    prompt: |
      You are Builder. Turn this idea note into a SPEC.md scaffold ...
    output:
      template: templates/spec_scaffold.md   # path relative to skills dir
      path: "20_Projects/{{slug}}/SPEC.md"    # path relative to vault base
    post_actions:
      - create_folder: "20_Projects/{{slug}}"
      - set_idea_state: project
      - notify: telegram

`SkillTrigger` and `SkillOutput` are intentionally tolerant of optional /
missing fields — Story 6.5 (scheduled/on-state triggers) is deferred, so a
minimal skill file (just `name` + `prompt` + `output`) is still valid.
`post_actions` is a list of single-key dicts (`{action_name: value}`), kept
as raw dicts here; `agents.builder` interprets them.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger("spore")

SKILL_FILE_GLOB = "*.skill.yaml"


class SkillTrigger(BaseModel):
    """Trigger config for a skill. All fields optional (Story 6.5 deferred —
    only manual invocation is wired up for now, but the schema accepts the
    full SPEC.md §4 shape so future stories don't need a migration)."""

    on_promote_to: str | None = None
    input_types: list[str] = Field(default_factory=list)
    on_capture: bool | None = None
    on_schedule: str | None = None
    manual: bool | None = None

    model_config = {"extra": "allow"}


class SkillOutput(BaseModel):
    """Where/how a skill's Builder output is written.

    `template` is a path relative to `skills_dir` (e.g.
    `templates/spec_scaffold.md`); `path` is a `{{var}}`-templated path
    relative to the vault base (e.g. `20_Projects/{{slug}}/SPEC.md`).
    """

    template: str | None = None
    path: str

    model_config = {"extra": "allow"}


class Skill(BaseModel):
    """A declarative skill loaded from a `*.skill.yaml` file."""

    name: str
    trigger: SkillTrigger = Field(default_factory=SkillTrigger)
    prompt: str = ""
    output: SkillOutput
    post_actions: list[dict] = Field(default_factory=list)

    model_config = {"extra": "allow"}


def load_skills(skills_dir: str | Path) -> dict[str, Skill]:
    """Scan `skills_dir` for `*.skill.yaml` files and parse each into a `Skill`.

    Returns a dict keyed by `Skill.name`. Files that are missing required
    fields or fail to parse raise a `ValueError` that names the offending
    file (so a single bad skill file fails loudly rather than being silently
    dropped, while still being a single, clearly-attributable error).
    """
    skills_path = Path(skills_dir)
    skills: dict[str, Skill] = {}

    if not skills_path.is_dir():
        logger.warning("skills_dir does not exist: %s", skills_path)
        return skills

    for file_path in sorted(skills_path.glob(SKILL_FILE_GLOB)):
        try:
            raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML in skill file {file_path}: {exc}") from exc

        if not isinstance(raw, dict):
            raise ValueError(f"skill file {file_path} must contain a YAML mapping")

        try:
            skill = Skill.model_validate(raw)
        except Exception as exc:  # pydantic.ValidationError
            raise ValueError(f"invalid skill schema in {file_path}: {exc}") from exc

        skills[skill.name] = skill

    return skills


def get_skill(name: str, skills: dict[str, Skill] | None = None, *, skills_dir: str | Path | None = None) -> Skill | None:
    """Look up a skill by name.

    If `skills` is not provided, loads from `skills_dir` (or
    `settings.skills_dir` if that's also omitted). Returns `None` if no
    skill with `name` is registered.
    """
    if skills is None:
        if skills_dir is None:
            from app.config import settings

            skills_dir = settings.skills_dir
        skills = load_skills(skills_dir)
    return skills.get(name)
