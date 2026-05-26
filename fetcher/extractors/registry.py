"""Host-suffix lookup table for ATS detection and extractor selection.
Returns an *ordered chain* of extractors to try; the generic extractor is
always last, so per-ATS extractors can return body_text=None to opt into
generic fallback without coordinating across modules."""

from __future__ import annotations

from fetcher.base import Extractor
from fetcher.extractors.ashby import AshbyExtractor
from fetcher.extractors.generic import GenericExtractor
from fetcher.extractors.greenhouse import GreenhouseExtractor
from fetcher.extractors.lever import LeverExtractor
from fetcher.extractors.workday import WorkdayExtractor

# Match by suffix on the lowercase host.
_ATS_BY_HOST_SUFFIX: tuple[tuple[str, str, type[Extractor]], ...] = (
    ("greenhouse.io", "greenhouse", GreenhouseExtractor),
    ("lever.co", "lever", LeverExtractor),
    ("ashbyhq.com", "ashby", AshbyExtractor),
    ("myworkdayjobs.com", "workday", WorkdayExtractor),
)


def ats_for_host(host: str) -> str:
    h = (host or "").lower()
    for suffix, ats, _ in _ATS_BY_HOST_SUFFIX:
        if h == suffix or h.endswith("." + suffix) or h.endswith(suffix):
            return ats
    return "generic"


def extractors_for_host(host: str) -> list[Extractor]:
    h = (host or "").lower()
    chain: list[Extractor] = []
    for suffix, _, cls in _ATS_BY_HOST_SUFFIX:
        if h == suffix or h.endswith("." + suffix) or h.endswith(suffix):
            chain.append(cls())
            break
    chain.append(GenericExtractor())
    return chain
