"""Resume version routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_session, require_auth
from api.resume import (
    SYSTEM_PROMPT,
    build_user_message,
    generate_tailored_resume,
    load_template,
    looks_like_tex,
    prompt_hash,
    resume_model,
    slugify,
)
from api.schemas import ResumeVersion as ResumeVersionSchema
from api.schemas import ResumeVersionSummary
from db.models import LLMCall, ResumeVersion, ScoredResult, SearchResult

router = APIRouter(prefix="/api", tags=["resumes"], dependencies=[Depends(require_auth)])


@router.get(
    "/applications/{application_id}/resumes",
    response_model=list[ResumeVersionSummary],
)
def list_resumes(
    application_id: int,
    session: Session = Depends(get_session),
) -> list[ResumeVersion]:
    _fetch_scored(session, application_id)
    return list(
        session.scalars(
            select(ResumeVersion)
            .where(ResumeVersion.scored_result_id == application_id)
            .order_by(ResumeVersion.generated_at.desc(), ResumeVersion.id.desc())
        )
    )


@router.post(
    "/applications/{application_id}/resumes",
    response_model=ResumeVersionSchema,
)
def generate_resume(
    application_id: int,
    force: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> ResumeVersion:
    scored, search = _fetch_scored_with_search(session, application_id)
    try:
        template = load_template()
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail="resume template not found") from e
    digest = prompt_hash(template, scored, search)

    if not force:
        existing = session.scalars(
            select(ResumeVersion)
            .where(
                ResumeVersion.scored_result_id == scored.id,
                ResumeVersion.prompt_hash == digest,
            )
            .order_by(ResumeVersion.generated_at.desc(), ResumeVersion.id.desc())
        ).first()
        if existing is not None:
            return existing

    model = resume_model()
    user_message = build_user_message(template, scored, search)
    tex_content, raw_response, latency_ms = generate_tailored_resume(user_message, model)
    if not looks_like_tex(tex_content):
        raise HTTPException(status_code=502, detail="Claude returned invalid LaTeX")

    llm_call = LLMCall(
        run_id=scored.run_id,
        batch_index=0,
        provider="anthropic",
        model=model,
        mode="resume_tailoring",
        attempt=1,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_message,
        raw_response=raw_response,
        parsed_ok=True,
        latency_ms=latency_ms,
    )
    session.add(llm_call)
    session.flush()

    version = ResumeVersion(
        scored_result_id=scored.id,
        llm_call_id=llm_call.id,
        tex_content=tex_content,
        model=model,
        prompt_hash=digest,
    )
    session.add(version)
    session.flush()
    return version


@router.get("/resumes/{version_id}", response_model=ResumeVersionSchema)
def get_resume(
    version_id: int,
    session: Session = Depends(get_session),
) -> ResumeVersion:
    return _fetch_resume(session, version_id)


@router.get("/resumes/{version_id}/download")
def download_resume(
    version_id: int,
    session: Session = Depends(get_session),
) -> Response:
    version = _fetch_resume(session, version_id)
    scored = _fetch_scored(session, version.scored_result_id)
    version_number = _version_number(session, version)
    company = slugify(scored.company, "company")
    role = slugify(scored.title, "role")
    filename = f"resume_{company}_{role}_v{version_number}.tex"
    return Response(
        content=version.tex_content,
        media_type="application/x-tex",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _fetch_scored(session: Session, application_id: int) -> ScoredResult:
    scored = session.get(ScoredResult, application_id)
    if scored is None:
        raise HTTPException(status_code=404, detail="application not found")
    return scored


def _fetch_scored_with_search(
    session: Session, application_id: int
) -> tuple[ScoredResult, SearchResult]:
    row = session.execute(
        select(ScoredResult, SearchResult)
        .join(SearchResult, ScoredResult.search_result_id == SearchResult.id)
        .where(ScoredResult.id == application_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="application not found")
    return row[0], row[1]


def _fetch_resume(session: Session, version_id: int) -> ResumeVersion:
    version = session.get(ResumeVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="resume version not found")
    return version


def _version_number(session: Session, version: ResumeVersion) -> int:
    version_ids = list(
        session.scalars(
            select(ResumeVersion.id)
            .where(ResumeVersion.scored_result_id == version.scored_result_id)
            .order_by(ResumeVersion.generated_at.asc(), ResumeVersion.id.asc())
        )
    )
    return version_ids.index(version.id) + 1
