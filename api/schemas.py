"""Pydantic schemas for API responses."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal[
    "discovered",
    "saved",
    "applied",
    "interview",
    "offer",
    "rejected",
    "ghosted",
    "irrelevant",
]

STATUSES: tuple[Status, ...] = (
    "discovered",
    "saved",
    "applied",
    "interview",
    "offer",
    "rejected",
    "ghosted",
    "irrelevant",
)


class LoginRequest(BaseModel):
    password: str


class OkResponse(BaseModel):
    ok: bool = True


class ApplicationPatch(BaseModel):
    status: Status | None = None
    notes: str | None = None
    applied_at: datetime | None = None


class Application(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    search_result_id: int
    llm_call_id: int
    is_job: bool
    title: str
    company: str
    location: str
    remote: bool
    score: int
    reason: str
    kept: bool
    status: Status
    notes: str | None
    applied_at: datetime | None
    status_updated_at: datetime
    created_at: datetime
    url: str
    search_title: str
    snippet: str
    engine: str
    query_text: str | None = None


class JobDescriptionDebug(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    normalized_url: str
    status: str
    http_status: int | None
    ats: str | None
    extractor: str
    body_text: str | None
    error: str | None
    latency_ms: int | None
    fetched_at: datetime


class LLMCallDebug(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    model: str
    mode: str
    attempt: int
    system_prompt: str
    user_prompt: str
    raw_response: dict | None = None
    latency_ms: int | None
    error: str | None


class JobEventDebug(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    stage: str
    level: str
    message: str
    details: dict | None = None
    created_at: datetime


class ApplicationDebug(BaseModel):
    source: str
    job_description: JobDescriptionDebug | None = None
    llm_call: LLMCallDebug | None = None
    events: list[JobEventDebug] = []


class ApplicationDetail(Application):
    resume_count: int = 0
    debug: ApplicationDebug | None = None


class ResumeVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scored_result_id: int
    llm_call_id: int | None
    generated_at: datetime
    model: str
    prompt_hash: str


class ResumeVersion(ResumeVersionSummary):
    tex_content: str


class StatusCounts(BaseModel):
    discovered: int = 0
    saved: int = 0
    applied: int = 0
    interview: int = 0
    offer: int = 0
    rejected: int = 0
    ghosted: int = 0
    irrelevant: int = 0


class ScoreBuckets(BaseModel):
    bucket_60_69: int = Field(0, alias="60-69")
    bucket_70_79: int = Field(0, alias="70-79")
    bucket_80_89: int = Field(0, alias="80-89")
    bucket_90_100: int = Field(0, alias="90-100")


class OverviewStats(BaseModel):
    total: int
    statuses: StatusCounts
    score_buckets: ScoreBuckets


class FunnelDay(BaseModel):
    day: date
    applied: int = 0
    interview: int = 0
    offer: int = 0


class SerperEstimate(BaseModel):
    query_count: int
    page_request_count: int
    results_per_query: int
    pages_per_query: int


class SerperRunStarted(SerperEstimate):
    run_id: int
    status: Literal["running"] = "running"


class SearchSourceExample(BaseModel):
    url: str
    score: int | None
    query_text: str | None
    application_id: int | None


class SearchSourceTopQuery(BaseModel):
    query_text: str
    count: int


class SearchSourceHost(BaseModel):
    host: str
    result_count: int
    scored_count: int
    avg_score: float | None
    max_score: int | None
    kept_count: int
    top_queries: list[SearchSourceTopQuery]
    examples: list[SearchSourceExample]


class SearchSourcesResponse(BaseModel):
    total_hosts: int
    hosts: list[SearchSourceHost]
