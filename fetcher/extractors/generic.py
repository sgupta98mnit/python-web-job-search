"""Generic main-content extractor backed by trafilatura. Used as the
default when no per-ATS extractor matches the URL host, and as the
fallback when a per-ATS extractor returns an empty result."""

from __future__ import annotations

import logging
import time

import trafilatura

from fetcher.base import ExtractorResult

log = logging.getLogger(__name__)


class GenericExtractor:
    name = "trafilatura"

    def extract(self, *, url: str, html: str) -> ExtractorResult:
        t0 = time.monotonic()
        body = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if body:
            body = body.strip()
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if body:
            log.info(
                "trafilatura parsed %s: %d chars in %dms (html=%d chars)",
                url, len(body), elapsed_ms, len(html or ""),
            )
        else:
            log.info(
                "trafilatura returned no body for %s in %dms (html=%d chars)",
                url, elapsed_ms, len(html or ""),
            )
        return ExtractorResult(body_text=body or None, extractor=self.name)
