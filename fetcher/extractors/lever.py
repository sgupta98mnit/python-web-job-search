"""Lever JD extractor. Targets jobs.lever.co/{org}/{id}."""

from __future__ import annotations

from bs4 import BeautifulSoup

from fetcher.base import ExtractorResult

_SELECTORS = ("div.posting-content", "div.section-wrapper.page-full-width")


class LeverExtractor:
    name = "lever_v1"

    def extract(self, *, url: str, html: str) -> ExtractorResult:
        soup = BeautifulSoup(html, "lxml")
        for sel in _SELECTORS:
            node = soup.select_one(sel)
            if node:
                text = node.get_text(separator="\n", strip=True)
                if text:
                    return ExtractorResult(body_text=text, extractor=self.name)
        return ExtractorResult(body_text=None, extractor=self.name)
