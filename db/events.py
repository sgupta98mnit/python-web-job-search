"""Helper for writing append-only pipeline events to job_events.

Events are keyed by normalized_url so they survive reruns and let you replay
the full processing history of any given job URL. Use sparingly: one event
per meaningful stage transition (fetch attempt, jina fallback, prefilter
decision, LLM scoring), not per log line.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.models import JobEvent


def record_event(
    session: Session,
    *,
    normalized_url: str,
    stage: str,
    run_id: int | None = None,
    level: str = "info",
    message: str = "",
    details: dict[str, Any] | None = None,
) -> JobEvent:
    """Append one event row. Caller is responsible for flushing/committing."""
    event = JobEvent(
        normalized_url=normalized_url,
        run_id=run_id,
        stage=stage,
        level=level,
        message=message,
        details=details,
    )
    session.add(event)
    return event
