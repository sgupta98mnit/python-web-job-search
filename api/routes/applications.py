"""Application tracking routes."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_session, require_auth
from api.schemas import (
    STATUSES,
    Application,
    ApplicationDebug,
    ApplicationDetail,
    ApplicationPatch,
    JobDescriptionDebug,
    JobEventDebug,
    LLMCallDebug,
    Status,
)
from db.models import (
    JobDescription,
    JobEvent,
    LLMCall,
    ResumeVersion,
    ScoredResult,
    SearchQuery,
    SearchResult,
)

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


SORT_OPTIONS = {
    "date_desc": (ScoredResult.created_at.desc(), ScoredResult.id.desc()),
    "date_asc": (ScoredResult.created_at.asc(), ScoredResult.id.asc()),
    "score_desc": (ScoredResult.score.desc(), ScoredResult.created_at.desc()),
    "score_asc": (ScoredResult.score.asc(), ScoredResult.created_at.desc()),
    "company_asc": (
        func.lower(ScoredResult.company).asc(),
        ScoredResult.created_at.desc(),
    ),
}


@router.get("", response_model=list[Application])
def list_applications(
    status: str | None = None,
    min_score: int | None = None,
    site: str | None = None,
    company: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = Query(default="date_desc"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    rejection_reason: str | None = None,
    session: Session = Depends(get_session),
) -> list[Application]:
    order_by = SORT_OPTIONS.get(sort)
    if order_by is None:
        raise HTTPException(
            status_code=422,
            detail=f"invalid sort: {sort} (allowed: {sorted(SORT_OPTIONS)})",
        )

    stmt = (
        select(ScoredResult, SearchResult, SearchQuery.query_text)
        .join(SearchResult, ScoredResult.search_result_id == SearchResult.id)
        .outerjoin(SearchQuery, SearchResult.query_id == SearchQuery.id)
        .order_by(*order_by)
        .limit(limit)
        .offset(offset)
    )
    statuses = _parse_statuses(status)
    if statuses:
        stmt = stmt.where(ScoredResult.status.in_(statuses))
    if min_score is not None:
        stmt = stmt.where(ScoredResult.score >= min_score)
    if site:
        stmt = stmt.where(func.lower(SearchResult.url).contains(site.lower()))
    if company:
        stmt = stmt.where(func.lower(ScoredResult.company).contains(company.lower()))
    if date_from is not None:
        start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        stmt = stmt.where(ScoredResult.created_at >= start)
    if date_to is not None:
        # Inclusive of the whole day.
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        stmt = stmt.where(ScoredResult.created_at < end)
    stmt = _apply_rejection_filter(stmt, rejection_reason)

    return [
        _application_from(scored, search, query_text)
        for scored, search, query_text in session.execute(stmt)
    ]


def _apply_rejection_filter(stmt, rejection_reason: str | None):
    """Filter by the rejection_reason column.

    omitted / "" / "none"  -> hide auto-rejected (rejection_reason IS NULL)
    "any"                  -> no filter (show everything)
    "auto"                 -> only auto-rejected (rejection_reason IS NOT NULL)
    "<tag>"                -> rows whose rejection_reason contains <tag>
    """
    value = (rejection_reason or "").strip().lower()
    if value in ("", "none"):
        return stmt.where(ScoredResult.rejection_reason.is_(None))
    if value == "any":
        return stmt
    if value == "auto":
        return stmt.where(ScoredResult.rejection_reason.is_not(None))
    return stmt.where(ScoredResult.rejection_reason.ilike(f"%{value}%"))


@router.get("/{application_id}", response_model=ApplicationDetail)
def get_application(
    application_id: int,
    session: Session = Depends(get_session),
) -> ApplicationDetail:
    scored, search, query_text = _fetch_application(session, application_id)
    return _application_detail_from(session, scored, search, query_text)


@router.patch("/{application_id}", response_model=ApplicationDetail)
def patch_application(
    application_id: int,
    body: ApplicationPatch,
    session: Session = Depends(get_session),
) -> ApplicationDetail:
    scored, search, query_text = _fetch_application(session, application_id)
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
    return _application_detail_from(session, scored, search, query_text)


def _fetch_application(
    session: Session, application_id: int
) -> tuple[ScoredResult, SearchResult, str | None]:
    row = session.execute(
        select(ScoredResult, SearchResult, SearchQuery.query_text)
        .join(SearchResult, ScoredResult.search_result_id == SearchResult.id)
        .outerjoin(SearchQuery, SearchResult.query_id == SearchQuery.id)
        .where(ScoredResult.id == application_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="application not found")
    return row[0], row[1], row[2]


def _application_detail_from(
    session: Session,
    scored: ScoredResult,
    search: SearchResult,
    query_text: str | None,
) -> ApplicationDetail:
    resume_count = session.scalar(
        select(func.count(ResumeVersion.id)).where(
            ResumeVersion.scored_result_id == scored.id
        )
    )
    jd = (
        session.get(JobDescription, scored.job_description_id)
        if scored.job_description_id is not None
        else None
    )
    llm = session.get(LLMCall, scored.llm_call_id)
    events = list(
        session.scalars(
            select(JobEvent)
            .where(JobEvent.normalized_url == search.normalized_url)
            .order_by(JobEvent.created_at.asc(), JobEvent.id.asc())
            .limit(500)
        )
    )
    debug = ApplicationDebug(
        source=scored.source,
        job_description=JobDescriptionDebug.model_validate(jd) if jd else None,
        llm_call=LLMCallDebug.model_validate(llm) if llm else None,
        events=[JobEventDebug.model_validate(e) for e in events],
    )
    return ApplicationDetail(
        **_application_from(scored, search, query_text).model_dump(),
        resume_count=int(resume_count or 0),
        debug=debug,
    )


def _application_from(
    scored: ScoredResult, search: SearchResult, query_text: str | None = None
) -> Application:
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
        query_text=query_text,
        rejection_reason=scored.rejection_reason,
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
