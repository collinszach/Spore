"""Corrections -> Sorter feedback loop (Story 9.2, FR37).

`recent_correction_examples` reads the K most recent `correction` rows
(original_json -> corrected_json, written by the review/redirect/merge
flows — Story 4.2/FR14) and formats each as a short few-shot guidance line
for the Sorter prompt. This is intentionally lightweight: no fine-tuning,
no embeddings — just recent human corrections surfaced as in-context
examples. Gated behind `settings.sorter_fewshot_enabled` (default False).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Correction


async def recent_correction_examples(session: AsyncSession, k: int = 5) -> list[dict]:
    """Return up to `k` most recent corrections, newest-first.

    Each item is `{"original": <dict|None>, "corrected": <dict|None>,
    "created_at": <datetime>}`. Rows with no `corrected_json` are skipped —
    there's nothing to learn from a correction that didn't change anything.
    """
    stmt = (
        select(Correction)
        .where(Correction.corrected_json.isnot(None))
        .order_by(Correction.created_at.desc())
        .limit(k)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    return [
        {
            "original": row.original_json,
            "corrected": row.corrected_json,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def format_fewshot_block(examples: list[dict]) -> str:
    """Render `examples` (as returned by `recent_correction_examples`) as a
    short prompt block. Returns "" if `examples` is empty."""
    if not examples:
        return ""

    lines = ["Recent corrections to learn from:"]
    for ex in examples:
        original = ex.get("original") or {}
        corrected = ex.get("corrected") or {}
        orig_type = original.get("type", "?")
        corr_type = corrected.get("type", "?")
        orig_tags = original.get("tags", [])
        corr_tags = corrected.get("tags", [])
        lines.append(
            f"- was: type={orig_type!r} tags={orig_tags!r} "
            f"-> corrected to: type={corr_type!r} tags={corr_tags!r}"
        )
    return "\n".join(lines)
