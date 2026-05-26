"""Ashby JD extractor. jobs.ashbyhq.com is a React SPA; the static HTML
sometimes contains the description and sometimes doesn't. We try the
static selector first, then fall back to Ashby's public posting API,
which returns the JD as `descriptionHtml`."""

from __future__ import annotations

from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import config
from fetcher.base import ExtractorResult

_API_TEMPLATE = "https://api.ashbyhq.com/posting-api/job-board/{org}/{posting_id}"


def parse_ashby_url(url: str) -> tuple[str, str] | None:
    """Extract (org, posting_id) from jobs.ashbyhq.com/{org}/{id}[/...]."""
    parsed = urlparse(url)
    if "ashbyhq.com" not in (parsed.netloc or "").lower():
        return None
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


class AshbyExtractor:
    name = "ashby_v1"

    def extract(self, *, url: str, html: str) -> ExtractorResult:
        soup = BeautifulSoup(html, "lxml")
        node = soup.select_one("div.posting-description, div._description_1ek5g_103")
        if node:
            text = node.get_text(separator="\n", strip=True)
            if text:
                return ExtractorResult(body_text=text, extractor=self.name)

        parsed = parse_ashby_url(url)
        if not parsed:
            return ExtractorResult(body_text=None, extractor=self.name)
        org, posting_id = parsed
        try:
            resp = requests.get(
                _API_TEMPLATE.format(org=org, posting_id=posting_id),
                timeout=config.JD_FETCH_TIMEOUT,
                headers={"User-Agent": config.JD_USER_AGENT},
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return ExtractorResult(body_text=None, extractor=self.name)

        posting = payload.get("jobPosting") or {}
        description_html = posting.get("descriptionHtml") or ""
        if not description_html:
            return ExtractorResult(body_text=None, extractor=self.name)
        text = BeautifulSoup(description_html, "lxml").get_text(
            separator="\n", strip=True
        )
        return ExtractorResult(
            body_text=text or None, extractor="ashby_v1_api"
        )
