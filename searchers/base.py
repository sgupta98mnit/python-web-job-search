"""Search backend interface. Every backend yields the same result dict shape."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Searcher(ABC):
    """One method: fetch a single page. Throttling + retries are handled
    by the caller in search.py.

    Optional batching: backends that can multiplex queries into one HTTP call
    set `supports_batch = True` and implement `fetch_batch`. `batch_max` caps
    the number of items per batch request.
    """

    backend_name: str = ""
    supports_batch: bool = False
    batch_max: int = 1

    @abstractmethod
    def fetch_page(
        self, query: str, pageno: int
    ) -> tuple[list[dict], list[list[str]]]:
        """Return (results, diagnostics).

        - `results` is a list of dicts with keys: title, url, snippet, engine.
        - `diagnostics` is backend-specific. For SearXNG this is the
          unresponsive_engines list ([[engine, reason], ...]). For Serper
          it's typically empty since Serper either returns results or 4xx/5xx.
        """
        raise NotImplementedError

    def fetch_batch(
        self, items: list[dict]
    ) -> list[tuple[list[dict], list[list[str]]]]:
        """Batched version of fetch_page. Each item is {"q": str, "page": int}.

        Returns a list parallel to `items`, each entry shaped like fetch_page's
        return. Default implementation raises - override on backends that
        support batching and set `supports_batch = True`.
        """
        raise NotImplementedError("this backend does not support batching")
