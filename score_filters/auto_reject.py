"""Post-LLM auto-rejection decision.

Runs after the LLM scores a job. Returns a comma-joined tag string when the
job should be auto-rejected, or None to leave the row alone. Callers persist
the returned tags to `ScoredResult.rejection_reason` and force `kept = False`.
"""

from __future__ import annotations

from .location_usa import is_usa_location


def auto_reject_reason(
    *,
    is_job: bool,
    score: int,
    location: str | None,
    remote: bool,
    min_score: int,
    enforce_usa: bool,
) -> str | None:
    """Return a comma-joined tag string explaining auto-rejection, or None.

    Non-job rows (is_job=False) are left alone -- they already have kept=False
    and a separate reason; tagging them with `low_score` would be redundant.
    """
    if not is_job:
        return None

    tags: list[str] = []
    if score < min_score:
        tags.append("low_score")
    if enforce_usa and is_usa_location(location, remote) is False:
        tags.append("non_usa_location")

    return ",".join(tags) if tags else None
