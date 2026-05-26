"""Generic main-content extractor backed by trafilatura. Used as the
default when no per-ATS extractor matches the URL host, and as the
fallback when a per-ATS extractor returns an empty result."""

from __future__ import annotations

import trafilatura

from fetcher.base import ExtractorResult


class GenericExtractor:
    name = "trafilatura"

    def extract(self, *, url: str, html: str) -> ExtractorResult:
        body = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if body:
            body = body.strip()
        return ExtractorResult(body_text=body or None, extractor=self.name)
