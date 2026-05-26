"""Workday JD extractor. Targets *.myworkdayjobs.com pages, which are
SPAs but include the JD body in the initial HTML for SEO."""

from __future__ import annotations

from bs4 import BeautifulSoup

from fetcher.base import ExtractorResult


class WorkdayExtractor:
    name = "workday_v1"

    def extract(self, *, url: str, html: str) -> ExtractorResult:
        soup = BeautifulSoup(html, "lxml")
        node = soup.select_one("div[data-automation-id='jobPostingDescription']")
        if node:
            text = node.get_text(separator="\n", strip=True)
            if text:
                return ExtractorResult(body_text=text, extractor=self.name)
        return ExtractorResult(body_text=None, extractor=self.name)
