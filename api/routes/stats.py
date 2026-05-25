"""Dashboard stats routes."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_session, require_auth
from api.schemas import STATUSES, FunnelDay, OverviewStats, ScoreBuckets, StatusCounts
from db.models import ScoredResult

router = APIRouter(
    prefix="/api/stats",
    tags=["stats"],
    dependencies=[Depends(require_auth)],
)


@router.get("/overview", response_model=OverviewStats)
def overview(session: Session = Depends(get_session)) -> OverviewStats:
    total = int(session.scalar(select(func.count(ScoredResult.id))) or 0)
    status_counts = {status: 0 for status in STATUSES}
    for status, count in session.execute(
        select(ScoredResult.status, func.count(ScoredResult.id)).group_by(ScoredResult.status)
    ):
        if status in status_counts:
            status_counts[status] = int(count)

    buckets = {
        "60-69": _count_score_range(session, 60, 69),
        "70-79": _count_score_range(session, 70, 79),
        "80-89": _count_score_range(session, 80, 89),
        "90-100": _count_score_range(session, 90, 100),
    }
    return OverviewStats(
        total=total,
        statuses=StatusCounts(**status_counts),
        score_buckets=ScoreBuckets.model_validate(buckets),
    )


@router.get("/funnel", response_model=list[FunnelDay])
def funnel(session: Session = Depends(get_session)) -> list[FunnelDay]:
    today = date.today()
    days = [today - timedelta(days=offset) for offset in range(29, -1, -1)]
    by_day = {day: {"applied": 0, "interview": 0, "offer": 0} for day in days}
    start = datetime.combine(days[0], time.min, tzinfo=timezone.utc)

    rows = session.execute(
        select(ScoredResult.status, ScoredResult.status_updated_at).where(
            ScoredResult.status.in_(["applied", "interview", "offer"]),
            ScoredResult.status_updated_at >= start,
        )
    )
    for status, updated_at in rows:
        day = updated_at.date()
        if day in by_day and status in by_day[day]:
            by_day[day][status] += 1

    return [FunnelDay(day=day, **counts) for day, counts in by_day.items()]


def _count_score_range(session: Session, low: int, high: int) -> int:
    return int(
        session.scalar(
            select(func.count(ScoredResult.id)).where(
                ScoredResult.score >= low,
                ScoredResult.score <= high,
            )
        )
        or 0
    )
