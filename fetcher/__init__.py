"""Job-description fetcher: pre-fetches and persists JD bodies, used by score.py."""

from fetcher.base import FetchOutcome
from fetcher.client import fetch_many

__all__ = ["FetchOutcome", "fetch_many"]
