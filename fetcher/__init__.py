"""Job-description fetcher: pre-fetches and persists JD bodies, used by score.py."""

from fetcher.base import FetchOutcome

try:
    from fetcher.client import fetch_many
except ModuleNotFoundError:
    # fetch_many will be available once fetcher.client is implemented (Task 11)
    fetch_many = None

__all__ = ["FetchOutcome", "fetch_many"]
