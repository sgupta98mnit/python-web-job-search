"""Shared interface for all LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


class ScoredJob(BaseModel):
    """Structured output for a single search result, judged by the LLM."""

    index: int = Field(..., description="0-based index into the input batch")
    is_job: bool = Field(..., description="True if this URL is an actual job posting")
    title: str = ""
    company: str = ""
    location: str = ""
    remote: bool = False
    score: int = Field(0, ge=0, le=100, description="Fit score, 0-100")
    reason: str = ""


# JSON schema shared by every provider for forced structured output.
SCORED_JOB_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "is_job": {"type": "boolean"},
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "location": {"type": "string"},
                    "remote": {"type": "boolean"},
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reason": {"type": "string"},
                },
                "required": [
                    "index",
                    "is_job",
                    "title",
                    "company",
                    "location",
                    "remote",
                    "score",
                    "reason",
                ],
            },
        }
    },
    "required": ["jobs"],
}


def build_user_prompt(results: list[dict], criteria: str) -> str:
    """Render a batch into a prompt. Indexes are local to the batch."""
    lines = ["CRITERIA:", criteria.strip(), "", "RESULTS:"]
    for i, r in enumerate(results):
        lines.append(f"[{i}] title: {r.get('title','')}")
        lines.append(f"    url: {r.get('url','')}")
        snip = (r.get("snippet") or "").replace("\n", " ")
        if len(snip) > 400:
            snip = snip[:400] + "..."
        lines.append(f"    snippet: {snip}")
    lines.append("")
    lines.append(
        "For each result, decide if it is an actual job posting (is_job), extract "
        "title/company/location/remote, and score it 0-100 against the CRITERIA. "
        "Return one object per input index. Be strict: aggregator pages, blog posts, "
        "and recruiter directories are not jobs."
    )
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You evaluate web search results for a job seeker. You return structured JSON "
    "only, matching the provided schema exactly. Never invent URLs or facts that "
    "are not supported by the snippet."
)


@dataclass
class LLMCallRecord:
    """Captures one HTTP request/response pair for audit/research."""

    mode: str            # "tool_call" | "json_only" | "json_only_retry"
    attempt: int         # 1-based attempt number across the whole batch
    system_prompt: str
    user_prompt: str
    raw_response: dict[str, Any] | None
    parsed_ok: bool
    latency_ms: int | None
    error: str | None


@dataclass
class BatchOutcome:
    """What `score_batch` returns: the parsed jobs plus the audit trail."""

    scored: list[ScoredJob] = field(default_factory=list)
    calls: list[LLMCallRecord] = field(default_factory=list)
    provider: str = ""
    model: str = ""


class LLMProvider(ABC):
    """All providers expose exactly one method."""

    provider_name: str = ""
    model: str = ""

    @abstractmethod
    def score_batch(self, results: list[dict], criteria: str) -> BatchOutcome:
        """Score one batch of search results. Must not raise on a bad LLM response -
        return a BatchOutcome with empty `scored` (and the failing call records)
        instead, so the pipeline survives."""
        raise NotImplementedError
