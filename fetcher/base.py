"""Types shared by the fetcher client, extractors, and tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

FetchStatus = Literal["ok", "http_error", "timeout", "unsupported", "parse_failed"]


@dataclass
class ExtractorResult:
    """Returned by an Extractor. `body_text=None` signals 'this extractor
    didn't find anything; try the next one (typically generic)'."""

    body_text: str | None
    extractor: str  # e.g. 'greenhouse_v1', 'trafilatura'


class Extractor(Protocol):
    name: str
    """Stable identifier persisted to job_descriptions.extractor."""

    def extract(self, *, url: str, html: str) -> ExtractorResult: ...


@dataclass
class FetchOutcome:
    """One row's worth of fetch state, returned by fetch_many."""

    status: FetchStatus
    ats: str  # 'greenhouse' | 'lever' | 'ashby' | 'workday' | 'generic'
    body_text: str | None
    http_status: int | None
    error: str | None
    latency_ms: int
    extractor: str
    job_description_id: int | None  # set after persistence
    # Pipeline events collected during this fetch (cache hit, native attempt,
    # jina fallback, etc.). Persisted to job_events by fetch_many on the main
    # thread - workers append here, main thread writes.
    events: list[dict[str, Any]] = field(default_factory=list)
