"""Greenhouse JD extractor. Targets the static HTML served by
boards.greenhouse.io/{org}/jobs/{id} and self-hosted greenhouse boards.
Returns body_text=None when no candidate selector matches; the registry
will then fall back to the generic extractor."""

from __future__ import annotations

from bs4 import BeautifulSoup

from fetcher.base import ExtractorResult

# Selectors tried in order. The first non-empty match wins.
_SELECTORS = ("div.content", "div.app-body", "section.content", "div#content")


class GreenhouseExtractor:
    name = "greenhouse_v1"

    def extract(self, *, url: str, html: str) -> ExtractorResult:
        soup = BeautifulSoup(html, "lxml")
        for sel in _SELECTORS:
            node = soup.select_one(sel)
            if node:
                text = node.get_text(separator="\n", strip=True)
                if text:
                    return ExtractorResult(body_text=text, extractor=self.name)
        return ExtractorResult(body_text=None, extractor=self.name)
