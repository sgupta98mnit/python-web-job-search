"""SQLAlchemy 2.x ORM models for the job-search pipeline.

Designed for research use: every search result, LLM request, and LLM response
is stored. JSONB columns let you slice raw payloads later without re-running.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    # running | succeeded | failed

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    criteria_text: Mapped[str] = mapped_column(Text, nullable=False)
    time_range: Mapped[str | None] = mapped_column(String(20))
    location: Mapped[str | None] = mapped_column(String(50))
    results_per_query: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False)
    min_score: Mapped[int] = mapped_column(Integer, nullable=False)

    total_results: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_kept: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    queries: Mapped[list["SearchQuery"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    results: Mapped[list["SearchResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    llm_calls: Mapped[list["LLMCall"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    scored: Mapped[list["ScoredResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    title_part: Mapped[str | None] = mapped_column(String(255))
    site_part: Mapped[str | None] = mapped_column(String(255))
    raw_result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    # List of [engine_name, reason] pairs reported as unresponsive by SearXNG.
    # Aggregated across all pages fetched for this query.
    unresponsive_engines: Mapped[Any | None] = mapped_column(JSONB)
    # Raw (pre-dedup) result count per page: {"1": 10, "2": 8, "3": 4}.
    # Lets you tune sites.txt `pages=N` by spotting where Google's yield drops off.
    page_counts: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="queries")
    results: Mapped[list["SearchResult"]] = relationship(back_populates="query")


class SearchResult(Base):
    __tablename__ = "search_results"
    __table_args__ = (
        UniqueConstraint("run_id", "normalized_url", name="uq_search_results_run_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_id: Mapped[int] = mapped_column(
        ForeignKey("search_queries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    snippet: Mapped[str] = mapped_column(Text, default="", nullable=False)
    engine: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="results")
    query: Mapped[SearchQuery] = relationship(back_populates="results")
    scored: Mapped[list["ScoredResult"]] = relationship(back_populates="search_result")


class LLMCall(Base):
    """One row per batched LLM request. Stores prompts + raw response verbatim."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    # "tool_call" | "json_only" | "json_only_retry"
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parsed_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="llm_calls")
    scored: Mapped[list["ScoredResult"]] = relationship(back_populates="llm_call")
    resume_versions: Mapped[list["ResumeVersion"]] = relationship(
        back_populates="llm_call"
    )


class ScoredResult(Base):
    """LLM-scored output. One row per (search_result, llm_call) pair."""

    __tablename__ = "scored_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    search_result_id: Mapped[int] = mapped_column(
        ForeignKey("search_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    llm_call_id: Mapped[int] = mapped_column(
        ForeignKey("llm_calls.id", ondelete="CASCADE"), nullable=False, index=True
    )

    is_job: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    company: Mapped[str] = mapped_column(Text, default="", nullable=False)
    location: Mapped[str] = mapped_column(Text, default="", nullable=False)
    remote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    kept: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="discovered", nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="scored")
    search_result: Mapped[SearchResult] = relationship(back_populates="scored")
    llm_call: Mapped[LLMCall] = relationship(back_populates="scored")
    resume_versions: Mapped[list["ResumeVersion"]] = relationship(
        back_populates="scored_result", cascade="all, delete-orphan"
    )
    email_notifications: Mapped[list["EmailNotification"]] = relationship(
        back_populates="scored_result", cascade="all, delete-orphan"
    )
    source: Mapped[str] = mapped_column(
        String(20), default="body", server_default="snippet", nullable=False
    )
    job_description_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_descriptions.id", ondelete="SET NULL"), index=True
    )

    job_description: Mapped["JobDescription | None"] = relationship(
        back_populates="scored"
    )


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scored_result_id: Mapped[int] = mapped_column(
        ForeignKey("scored_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    llm_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_calls.id", ondelete="SET NULL"), index=True
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    tex_content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    scored_result: Mapped[ScoredResult] = relationship(
        back_populates="resume_versions"
    )
    llm_call: Mapped[LLMCall | None] = relationship(
        back_populates="resume_versions"
    )


class EmailNotification(Base):
    __tablename__ = "email_notifications"
    __table_args__ = (
        UniqueConstraint(
            "recipient",
            "normalized_url",
            name="uq_email_notifications_recipient_url",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scored_result_id: Mapped[int] = mapped_column(
        ForeignKey("scored_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scored_result: Mapped[ScoredResult] = relationship(
        back_populates="email_notifications"
    )


class JobEvent(Base):
    """Append-only audit log of pipeline events keyed by normalized_url.

    One row per stage transition (fetch attempt, jina fallback, prefilter
    decision, LLM scoring, etc.). Lets us replay the full processing
    history of any given job URL across runs.
    """

    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    level: Mapped[str] = mapped_column(String(10), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobDescription(Base):
    __tablename__ = "job_descriptions"
    __table_args__ = (
        UniqueConstraint("normalized_url", name="uq_job_descriptions_normalized_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'ok' | 'http_error' | 'timeout' | 'unsupported' | 'parse_failed'
    http_status: Mapped[int | None] = mapped_column(Integer)
    ats: Mapped[str | None] = mapped_column(String(20))
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html_sha256: Mapped[str | None] = mapped_column(String(64))
    extractor: Mapped[str] = mapped_column(String(40), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    scored: Mapped[list["ScoredResult"]] = relationship(
        back_populates="job_description"
    )
