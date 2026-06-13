"""Epic 9 — cost dashboard (9.1) and ops metrics (9.3) aggregations.

All queries are set-based (GROUP BY / aggregate functions) against the
existing tables — no per-row Python loops over the DB, no N+1.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Date, Numeric, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note, RawCapture, Reminder, ReviewItem, SkillRun


async def cost_summary(session: AsyncSession) -> dict:
    """Story 9.1 — aggregate `skill_run` for the cost dashboard."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    cost_expr = func.coalesce(func.sum(SkillRun.cost_usd), 0)

    total_usd = (await session.execute(select(cost_expr))).scalar_one()

    this_week_usd = (
        await session.execute(select(cost_expr).where(SkillRun.created_at >= week_ago))
    ).scalar_one()

    by_skill_rows = (
        await session.execute(
            select(
                SkillRun.skill,
                func.count().label("runs"),
                func.coalesce(func.sum(SkillRun.tokens_in), 0).label("tokens_in"),
                func.coalesce(func.sum(SkillRun.tokens_out), 0).label("tokens_out"),
                cost_expr.label("cost_usd"),
            )
            .group_by(SkillRun.skill)
            .order_by(SkillRun.skill)
        )
    ).all()

    fourteen_days_ago = now - timedelta(days=14)
    day_expr = cast(SkillRun.created_at, Date)
    by_day_rows = (
        await session.execute(
            select(
                day_expr.label("day"),
                cost_expr.label("cost_usd"),
                func.count().label("runs"),
            )
            .where(SkillRun.created_at >= fourteen_days_ago)
            .group_by(day_expr)
            .order_by(day_expr)
        )
    ).all()

    by_model_rows = (
        await session.execute(
            select(
                SkillRun.model,
                func.count().label("runs"),
                cost_expr.label("cost_usd"),
            )
            .group_by(SkillRun.model)
            .order_by(SkillRun.model)
        )
    ).all()

    return {
        "total_usd": float(total_usd),
        "this_week_usd": float(this_week_usd),
        "by_skill": [
            {
                "skill": row.skill,
                "runs": int(row.runs),
                "tokens_in": int(row.tokens_in),
                "tokens_out": int(row.tokens_out),
                "cost_usd": float(row.cost_usd),
            }
            for row in by_skill_rows
        ],
        "by_day": [
            {
                "day": row.day.isoformat(),
                "cost_usd": float(row.cost_usd),
                "runs": int(row.runs),
            }
            for row in by_day_rows
        ],
        "by_model": [
            {
                "model": row.model,
                "runs": int(row.runs),
                "cost_usd": float(row.cost_usd),
            }
            for row in by_model_rows
        ],
    }


async def ops_metrics(session: AsyncSession) -> dict:
    """Story 9.3 — pipeline/ops metrics (ARCHITECTURE §9).

    gate_distribution derivation (documented per Epic 9 instructions):

    The confidence gate (agents/gate.py) doesn't persist its decision
    directly, so we approximate the {direct_write, needs_review,
    review_floor} distribution from the rows it produces:

    - review_floor: `review_item` rows with reason='low_confidence' whose
      capture has NO corresponding `note` (i.e. confidence was below
      REVIEW_FLOOR and the gate created review-only, no note).
    - needs_review: `note` rows whose `tags` array contains 'needs-review'
      (the gate tags mid-confidence notes this way per gate.NEEDS_REVIEW_TAG).
    - direct_write: all other notes — i.e. notes NOT tagged 'needs-review'.
      (By construction every note the gate creates has either the
      needs-review tag or was a high-confidence direct write, so this is
      `total_notes - needs_review_notes`.)

    This is a calibratable approximation, not an exact replay of gate.route
    decisions — it's intended as a rough distribution metric over time.
    """
    today = datetime.now(timezone.utc).date()
    today_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

    captures_today = (
        await session.execute(
            select(func.count())
            .select_from(RawCapture)
            .where(RawCapture.created_at >= today_start)
        )
    ).scalar_one()

    status_rows = (
        await session.execute(
            select(RawCapture.status, func.count()).group_by(RawCapture.status)
        )
    ).all()
    captures_by_status = {row[0]: int(row[1]) for row in status_rows}

    # needs_review: notes tagged 'needs-review'.
    needs_review_count = (
        await session.execute(
            select(func.count())
            .select_from(Note)
            .where(Note.tags.any("needs-review"))
        )
    ).scalar_one()

    total_notes = (await session.execute(select(func.count()).select_from(Note))).scalar_one()

    direct_write_count = int(total_notes) - int(needs_review_count)

    # review_floor: open or resolved review_items with reason='low_confidence'
    # whose capture has no note at all (gate created review-only, no note).
    review_floor_count = (
        await session.execute(
            select(func.count())
            .select_from(ReviewItem)
            .where(
                ReviewItem.reason == "low_confidence",
                ~ReviewItem.capture_id.in_(
                    select(Note.source_capture_id).where(Note.source_capture_id.isnot(None))
                ),
            )
        )
    ).scalar_one()

    review_queue_depth = (
        await session.execute(
            select(func.count()).select_from(ReviewItem).where(ReviewItem.status == "open")
        )
    ).scalar_one()

    idea_state_rows = (
        await session.execute(
            select(Note.idea_state, func.count()).group_by(Note.idea_state)
        )
    ).all()
    notes_by_idea_state = {(row[0] or "unknown"): int(row[1]) for row in idea_state_rows}

    reminders_scheduled = (
        await session.execute(
            select(func.count()).select_from(Reminder).where(Reminder.status == "scheduled")
        )
    ).scalar_one()

    cost_today_usd = (
        await session.execute(
            select(func.coalesce(func.sum(SkillRun.cost_usd), 0)).where(
                SkillRun.created_at >= today_start
            )
        )
    ).scalar_one()

    return {
        "captures_today": int(captures_today),
        "captures_by_status": captures_by_status,
        "gate_distribution": {
            "direct_write": direct_write_count,
            "needs_review": int(needs_review_count),
            "review_floor": int(review_floor_count),
        },
        "review_queue_depth": int(review_queue_depth),
        "notes_by_idea_state": notes_by_idea_state,
        "reminders_scheduled": int(reminders_scheduled),
        "cost_today_usd": float(cost_today_usd),
    }
