"""Serper.dev backend (Google results via paid API).

API: POST https://google.serper.dev/search
Headers: X-API-KEY: <key>, Content-Type: application/json
Body: {"q": "...", "page": 1, "num": 10, "gl": "us", "hl": "en", "tbs": "qdr:d"}
Response: {"organic": [{title, link, snippet, ...}], ...}
"""

from __future__ import annotations

import json
import logging

import requests

import config

from .base import Searcher

log = logging.getLogger(__name__)


# SearXNG-style time ranges -> Google's tbs= shorthand.
_TBS = {
    "day": "qdr:d",
    "week": "qdr:w",
    "month": "qdr:m",
    "year": "qdr:y",
}


class SerperSearcher(Searcher):
    backend_name = "serper"
    supports_batch = True
    batch_max = 100  # Serper accepts up to 100 queries per POST

    def __init__(
        self,
        url: str,
        api_key: str,
        country: str,
        language: str,
        num_per_page: int = 10,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "SERPER_API_KEY is required for the serper backend - "
                "set it in .env or your environment."
            )
        self.url = url
        self.api_key = api_key
        self.country = country
        self.language = language
        self.num_per_page = num_per_page

    def _build_entry(self, query: str, pageno: int) -> dict[str, object]:
        entry: dict[str, object] = {
            "q": query,
            "page": pageno,
            "num": self.num_per_page,
            "gl": self.country,
            "hl": self.language,
        }
        if config.TIME_RANGE and config.TIME_RANGE in _TBS:
            entry["tbs"] = _TBS[config.TIME_RANGE]
        return entry

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "job-search-cli/1.0",
        }

    @staticmethod
    def _parse_response(data: dict) -> list[dict]:
        # Serper returns 200 OK even for per-entry failures (e.g. free-tier
        # rejecting num>10). Surface those so callers see them, not 0 results.
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise RuntimeError(f"Serper error: {msg}")
        organic = data.get("organic") or []
        results: list[dict] = []
        for item in organic:
            url = (item.get("link") or "").strip()
            if not url:
                continue
            results.append(
                {
                    "title": (item.get("title") or "").strip(),
                    "url": url,
                    "snippet": (item.get("snippet") or "").strip(),
                    "engine": "google (serper)",
                }
            )
        return results

    def fetch_page(
        self, query: str, pageno: int
    ) -> tuple[list[dict], list[list[str]]]:
        r = requests.post(
            self.url,
            data=json.dumps(self._build_entry(query, pageno)),
            headers=self._headers(),
            timeout=30,
        )
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError as e:
            raise RuntimeError("non-JSON response from Serper") from e
        return self._parse_response(data), []

    def fetch_batch(
        self, items: list[dict]
    ) -> list[tuple[list[dict], list[list[str]]]]:
        if not items:
            return []
        if len(items) > self.batch_max:
            raise ValueError(
                f"Serper batch size {len(items)} exceeds cap {self.batch_max}"
            )
        body = [self._build_entry(it["q"], it.get("page", 1)) for it in items]
        r = requests.post(
            self.url,
            data=json.dumps(body),
            headers=self._headers(),
            timeout=60,
        )
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError as e:
            raise RuntimeError("non-JSON response from Serper") from e
        if not isinstance(data, list) or len(data) != len(items):
            raise RuntimeError(
                f"Serper batch response shape mismatch: "
                f"got {type(data).__name__} len={len(data) if hasattr(data, '__len__') else '?'}, "
                f"expected list of {len(items)}"
            )
        # Per-entry errors (e.g. one query rejected) shouldn't kill the batch.
        # Log them and return empty results for that entry.
        out: list[tuple[list[dict], list[list[str]]]] = []
        for it, resp in zip(items, data):
            try:
                out.append((self._parse_response(resp), []))
            except RuntimeError as e:
                log.warning("Serper batch entry q=%r page=%s: %s", it.get("q"), it.get("page"), e)
                out.append(([], [["serper", str(e)]]))
        return out
