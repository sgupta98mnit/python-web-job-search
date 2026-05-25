"""Application tracking routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_session, require_auth
from api.schemas import (
    STATUSES,
    Application,
    ApplicationDetail,
    ApplicationPatch,
    Status,
)
from db.models import ResumeVersion, ScoredResult, SearchResult

router = APIRouter(
    prefix="/api/applications",
    tags=["applications"],
    dependencies=[Depends(require_auth)],
)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "discovered": {"saved", "applied", "rejected", "ghosted", "irrelevant"},
    "saved": {"applied", "rejected", "ghosted", "irrelevant"},
    "applied": {"interview", "offer", "rejected", "ghosted", "irrelevant"},
    "interview": {"offer", "rejected", "ghosted", "irrelevant"},
    "offer": {"rejected", "irrelevant"},
    "rejected": {"applied", "irrelevant"},
    "ghosted": {"applied", "interview", "rejected", "irrelevant"},
    "irrelevant": {"discovered", "saved"},
}


@router.get("", response_model=list[Application])
def list_applications(
    status: str | None = None,
    min_score: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[Application]:
    stmt = (
        select(ScoredResult, SearchResult)
        .join(SearchResult, ScoredResult.search_result_id == SearchResult.id)
        .order_by(ScoredResult.created_at.desc(), ScoredResult.id.desc())
        .limit(limit)
        .offset(offset)
    )
    statuses = _parse_statuses(status)
    if statuses:
        stmt = stmt.where(ScoredResult.status.in_(statuses))
    if min_score is not None:
        stmt = stmt.where(ScoredResult.score >= min_score)

    return [_application_from(scored, search) for scored, search in session.execute(stmt)]


@router.get("/{application_id}", response_model=ApplicationDetail)
def get_application(
    application_id: int,
    session: Session = Depends(get_session),
) -> ApplicationDetail:
    scored, search = _fetch_application(session, application_id)
    return _application_detail_from(session, scored, search)


@router.patch("/{application_id}", response_model=ApplicationDetail)
def patch_application(
    application_id: int,
    body: ApplicationPatch,
    session: Session = Depends(get_session),
) -> ApplicationDetail:
    scored, search = _fetch_application(session, application_id)
    changes = body.model_dump(exclude_unset=True)
    now = datetime.now(timezone.utc)

    if "status" in changes and changes["status"] is not None:
        _validate_transition(scored.status, changes["status"])
        scored.status = changes["status"]
        if changes["status"] == "applied" and "applied_at" not in changes and scored.applied_at is None:
            scored.applied_at = now

    if "notes" in changes:
        scored.notes = changes["notes"]
    if "applied_at" in changes:
        scored.applied_at = changes["applied_at"]
    if changes:
        scored.status_updated_at = now

    session.flush()
    return _application_detail_from(session, scored, search)


def _fetch_application(session: Session, application_id: int) -> tuple[ScoredResult, SearchResult]:
    row = session.execute(
        select(ScoredResult, SearchResult)
        .join(SearchResult, ScoredResult.search_result_id == SearchResult.id)
        .where(ScoredResult.id == application_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="application not found")
    return row[0], row[1]


def _application_detail_from(
    session: Session, scored: ScoredResult, search: SearchResult
) -> ApplicationDetail:
    resume_count = session.scalar(
        select(func.count(ResumeVersion.id)).where(
            ResumeVersion.scored_result_id == scored.id
        )
    )
    return ApplicationDetail(
        **_application_from(scored, search).model_dump(),
        resume_count=int(resume_count or 0),
    )


def _application_from(scored: ScoredResult, search: SearchResult) -> Application:
    return Application(
        id=scored.id,
        run_id=scored.run_id,
        search_result_id=scored.search_result_id,
        llm_call_id=scored.llm_call_id,
        is_job=scored.is_job,
        title=scored.title,
        company=scored.company,
        location=scored.location,
        remote=scored.remote,
        score=scored.score,
        reason=scored.reason,
        kept=scored.kept,
        status=scored.status,
        notes=scored.notes,
        applied_at=scored.applied_at,
        status_updated_at=scored.status_updated_at,
        created_at=scored.created_at,
        url=search.url,
        search_title=search.title,
        snippet=search.snippet,
        engine=search.engine,
    )


def _parse_statuses(raw: str | None) -> list[Status]:
    if not raw:
        return []
    statuses = [part.strip() for part in raw.split(",") if part.strip()]
    invalid = [value for value in statuses if value not in STATUSES]
    if invalid:
        raise HTTPException(status_code=422, detail=f"invalid status: {invalid[0]}")
    return statuses  # type: ignore[return-value]


def _validate_transition(current: str, next_status: str) -> None:
    if current == next_status:
        return
    if next_status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=422,
            detail=f"cannot transition from {current} to {next_status}",
        )
