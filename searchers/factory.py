"""Build the right Searcher from config. Mirrors providers/factory.py."""

from __future__ import annotations

import os

import config

from .base import Searcher
from .searxng import SearXNGSearcher
from .serper import SerperSearcher


def build_searcher(name: str | None = None) -> Searcher:
    name = name or config.SEARCH_BACKEND
    if name not in config.SEARCH_PRESETS:
        raise ValueError(
            f"Unknown search backend {name!r}. Known: {sorted(config.SEARCH_PRESETS)}"
        )
    preset = config.SEARCH_PRESETS[name]
    kind = preset["kind"]

    if kind == "searxng":
        return SearXNGSearcher(url=str(preset["url"]))
    if kind == "serper":
        key_env = preset.get("key_env")
        api_key = os.getenv(key_env) if key_env else None
        return SerperSearcher(
            url=str(preset["url"]),
            api_key=api_key or "",
            country=str(preset.get("country", "us")),
            language=str(preset.get("language", "en")),
            num_per_page=int(preset.get("num_per_page") or 10),
        )
    raise ValueError(f"Unknown searcher kind: {kind!r}")
