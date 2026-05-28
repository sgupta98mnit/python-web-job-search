"""SearXNG backend. Single-page fetch; throttling is added by the caller."""

from __future__ import annotations

import requests

import config

from .base import Searcher


class SearXNGSearcher(Searcher):
    backend_name = "searxng"

    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")

    def fetch_page(
        self, query: str, pageno: int
    ) -> tuple[list[dict], list[list[str]]]:
        params: dict[str, str | int] = {
            "q": query,
            "format": "json",
            "engines": "google",
            "safesearch": 0,
            "language": "en-US",
            "pageno": pageno,
        }
        if config.TIME_RANGE:
            params["time_range"] = config.TIME_RANGE

        r = requests.get(
            f"{self.url}/search",
            params=params,
            timeout=30,
            headers={"User-Agent": "job-search-cli/1.0"},
        )
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError as e:
            raise RuntimeError("non-JSON response from SearXNG") from e

        results = [
            {
                "title": (item.get("title") or "").strip(),
                "url": (item.get("url") or "").strip(),
                "snippet": (item.get("content") or "").strip(),
                "engine": item.get("engine", ""),
            }
            for item in data.get("results", [])
        ]

        raw_unresp = data.get("unresponsive_engines") or []
        unresp: list[list[str]] = []
        for entry in raw_unresp:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                unresp.append([str(entry[0]), str(entry[1])])
            else:
                unresp.append([str(entry), ""])
        return results, unresp
