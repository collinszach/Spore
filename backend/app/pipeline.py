"""Pure idea-pipeline state-machine logic (Story 7.1).

`Note.idea_state` (001_init.sql) is one of:
    seedling | sapling | sprout | project | shipped | archived

`ALLOWED_TRANSITIONS` maps each state to the set of states it may move to.
This module has no DB/IO dependencies so it can be unit-tested in isolation.
"""

from __future__ import annotations

# Forward pipeline: seedling -> sapling -> sprout -> project -> shipped.
# Any non-terminal state may also be archived directly; sapling/sprout can
# additionally move back one step; archived can be revived back to seedling.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "seedling": {"sapling", "archived"},
    "sapling": {"sprout", "seedling", "archived"},
    "sprout": {"project", "sapling", "archived"},
    "project": {"shipped", "archived"},
    "shipped": {"archived"},
    "archived": {"seedling"},
}

# The single "next step forward" for each state, used by the promotion-
# suggestion rule (Story 7.3). States with no forward transition (shipped,
# archived) are absent.
NEXT_FORWARD_STATE: dict[str, str] = {
    "seedling": "sapling",
    "sapling": "sprout",
    "sprout": "project",
    "project": "shipped",
}

ALL_STATES: tuple[str, ...] = (
    "seedling",
    "sapling",
    "sprout",
    "project",
    "shipped",
    "archived",
)


def can_transition(from_state: str, to_state: str) -> bool:
    """Return True if `from_state -> to_state` is an allowed transition."""
    return to_state in ALLOWED_TRANSITIONS.get(from_state, set())


def next_forward_state(current_state: str) -> str | None:
    """Return the next "promote" state for `current_state`, or None if terminal."""
    return NEXT_FORWARD_STATE.get(current_state)
