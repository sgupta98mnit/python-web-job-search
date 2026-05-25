"""Query expansion + DB persistence of every search.

The actual page-fetching is delegated to a `Searcher` backend (SearXNG, Serper)
selected via config.SEARCH_BACKEND. This module owns: query expansion,
throttling, retries, dedup, persistence, and the run-end summary.

Throttling strategy:
- Jittered minimum delay between requests (page-to-page and query-to-query).
- Sliding-window cap on requests per minute, enforced globally.
- Exponential backoff on HTTP 429/5xx and request errors.
- Optional cool-off after N consecutive zero-result queries (sign of engine
  CAPTCHA/block).
"""

from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlparse, urlunparse

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from db.models import Run, SearchQuery, SearchResult
from searchers.base import Searcher
from searchers.factory import build_searcher

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Throttling
# ---------------------------------------------------------------------------
class _Throttle:
    """Sliding-window per-minute cap + jittered minimum spacing between calls."""

    def __init__(self, rpm: int) -> None:
        self.rpm = max(1, rpm)
        self.window: list[float] = []

    def _wait_window(self) -> None:
        now = time.monotonic()
        self.window = [t for t in self.window if now - t < 60.0]
        if len(self.window) >= self.rpm:
            sleep_for = 60.0 - (now - self.window[0]) + 0.05
            if sleep_for > 0:
                log.info("Throttle: %d/min cap reached, sleeping %.1fs", self.rpm, sleep_for)
                time.sleep(sleep_for)

    def acquire(self, base_delay: float | None = None) -> None:
        """Sleep for `base_delay * (1 +/- jitter)`, then enforce per-minute cap."""
        if base_delay and base_delay > 0:
            j = config.THROTTLE_JITTER
            mult = 1.0 + random.uniform(-j, j) if j > 0 else 1.0
            time.sleep(max(0.0, base_delay * mult))
        self._wait_window()
        self.window.append(time.monotonic())


_throttle = _Throttle(config.MAX_REQUESTS_PER_MINUTE)


# Lazy: built on first use so the import of `config.SEARCH_BACKEND` can change
# before any search happens (smoke tests, etc.). Reset with `reset_searcher()`.
_searcher: Searcher | None = None


def _get_searcher() -> Searcher:
    global _searcher
    if _searcher is None:
        _searcher = build_searcher()
        log.info("Search backend: %s", _searcher.backend_name)
    return _searcher


def reset_searcher() -> None:
    global _searcher
    _searcher = None


# ---------------------------------------------------------------------------
# Query loading + N x M expansion
# ---------------------------------------------------------------------------
def _read_lines(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f]
    except FileNotFoundError:
        return []
    return [ln for ln in lines if ln and not ln.startswith("#")]


def _parse_site_line(line: str) -> tuple[str, int | None]:
    """Parse 'site:foo | pages=2' -> ('site:foo', 2). No suffix -> (line, None)."""
    if "|" not in line:
        return line, None
    site_part, _, rest = line.rpartition("|")
    site_part = site_part.strip()
    rest = rest.strip()
    if rest.startswith("pages="):
        try:
            n = int(rest.split("=", 1)[1])
            if n > 0:
                return site_part, n
        except ValueError:
            pass
    log.warning("Unrecognized site suffix %r; treating whole line as site", rest)
    return line, None


def _read_sites(path: str) -> list[tuple[str, int | None]]:
    return [_parse_site_line(ln) for ln in _read_lines(path)]


def load_titles(titles_path: str = "titles.txt") -> list[str]:
    """Read titles.txt verbatim. Exposed so callers (e.g. daemon) can count
    them for round-robin rotation."""
    return _read_lines(titles_path)


def build_queries(
    titles_path: str = "titles.txt",
    sites_path: str = "sites.txt",
    queries_path: str = "queries.txt",
    title_indices: list[int] | None = None,
) -> list[tuple[str, str | None, str | None, int | None]]:
    """Return list of (query_text, title_part, site_part, pages_override).

    If `queries.txt` has any non-comment lines, those are used verbatim
    (title_part/site_part/pages_override = None). Otherwise we cross
    titles x sites and append the LOCATION suffix. Per-site page overrides
    come from `| pages=N` suffixes in sites.txt.

    `title_indices`: if given, only use titles at those indices. Lets the
    daemon mode cycle through one title per run instead of all N.
    """
    override = _read_lines(queries_path)
    if override:
        return [(q, None, None, None) for q in override]

    titles = _read_lines(titles_path)
    sites = _read_sites(sites_path)
    if not titles or not sites:
        return []

    if title_indices is not None:
        titles = [titles[i] for i in title_indices if 0 <= i < len(titles)]
        if not titles:
            return []

    loc = config.LOCATION.strip()
    out: list[tuple[str, str | None, str | None, int | None]] = []
    for t in titles:
        for s, pages in sites:
            q = f"{t} {s} {loc}".strip()
            out.append((q, t, s, pages))
    return out


def _load_seen_urls(session: Session, window_days: int) -> set[str]:
    """URLs we've already stored within the last `window_days`. Used to skip
    re-inserting (and re-scoring) the same job across daemon iterations."""
    if window_days <= 0:
        return set()
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = session.execute(
        select(SearchResult.normalized_url).where(SearchResult.created_at >= cutoff)
    ).all()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------
def _normalize_url(url: str) -> str:
    """Lowercase host, strip query/fragment, trim trailing slash."""
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        path = (p.path or "").rstrip("/")
        return urlunparse((p.scheme.lower(), host, path, "", "", ""))
    except Exception:
        return url


# ---------------------------------------------------------------------------
# SearXNG request (single page)
# ---------------------------------------------------------------------------
def _fetch_page_once(query: str, pageno: int) -> tuple[list[dict], list[list[str]]]:
    """Delegate to the configured Searcher. Raises on transport/4xx/5xx errors,
    which the retry layer in `fetch_page` handles.
    """
    return _get_searcher().fetch_page(query, pageno)


def fetch_page(
    query: str, pageno: int, *, inter_request_delay: float
) -> tuple[list[dict], list[list[str]]]:
    """Throttled + retried single-page fetch. See `_fetch_page_once` for return shape."""
    last_exc: Exception | None = None
    for attempt in range(1, config.RETRY_MAX_ATTEMPTS + 1):
        _throttle.acquire(base_delay=inter_request_delay if attempt == 1 else 0.0)
        try:
            return _fetch_page_once(query, pageno)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            transient = code == 429 or 500 <= code < 600
            last_exc = e
            if not transient or attempt == config.RETRY_MAX_ATTEMPTS:
                log.warning(
                    "SearXNG HTTP %s for %r page=%d (giving up after %d)",
                    code, query, pageno, attempt,
                )
                raise
            backoff = min(
                config.RETRY_BACKOFF_MAX,
                config.RETRY_BACKOFF_BASE * (2 ** (attempt - 1)),
            )
            log.warning(
                "SearXNG HTTP %s for %r page=%d, retrying in %.1fs (attempt %d/%d)",
                code, query, pageno, backoff, attempt, config.RETRY_MAX_ATTEMPTS,
            )
            time.sleep(backoff)
        except (requests.RequestException, RuntimeError) as e:
            last_exc = e
            if attempt == config.RETRY_MAX_ATTEMPTS:
                log.warning(
                    "SearXNG request failed for %r page=%d (giving up after %d): %s",
                    query, pageno, attempt, e,
                )
                raise
            backoff = min(
                config.RETRY_BACKOFF_MAX,
                config.RETRY_BACKOFF_BASE * (2 ** (attempt - 1)),
            )
            log.warning(
                "SearXNG transient error for %r page=%d, retrying in %.1fs: %s",
                query, pageno, backoff, e,
            )
            time.sleep(backoff)
    # Unreachable; loop either returns or raises.
    raise last_exc if last_exc else RuntimeError("fetch_page exhausted")


def run_query(
    query: str,
    first_page_delay: float = 0.0,
    max_pages: int | None = None,
) -> tuple[list[tuple[int, dict]], list[list[str]]]:
    """Fetch up to `max_pages` (or PAGES_PER_QUERY) pages, capped at
    RESULTS_PER_QUERY total.

    Returns (collected_results, unresponsive_engines_across_pages). The
    unresponsive list is deduped by (engine, reason).
    """
    collected: list[tuple[int, dict]] = []
    unresp_seen: set[tuple[str, str]] = set()
    unresp_merged: list[list[str]] = []

    pages = max_pages if max_pages is not None else config.PAGES_PER_QUERY
    for pageno in range(1, pages + 1):
        delay = first_page_delay if pageno == 1 else config.SECONDS_BETWEEN_PAGES
        try:
            page, unresp = fetch_page(query, pageno, inter_request_delay=delay)
        except Exception:
            if not collected:
                raise
            break
        for entry in unresp:
            key = (entry[0], entry[1])
            if key not in unresp_seen:
                unresp_seen.add(key)
                unresp_merged.append(entry)
        if not page:
            break
        for item in page:
            collected.append((pageno, item))
            if len(collected) >= config.RESULTS_PER_QUERY:
                return collected, unresp_merged
    return collected, unresp_merged


# ---------------------------------------------------------------------------
# Pipeline: run all queries, persist everything, return SearchResult IDs + data
# ---------------------------------------------------------------------------
def search_all(
    session: Session,
    run: Run,
    *,
    title_indices: list[int] | None = None,
    dedup_window_days: int = 30,
) -> list[SearchResult]:
    """Run every query for this Run, persist queries + results, dedup by URL.

    Returns the SearchResult ORM objects (already flushed and with IDs).
    Routes to the batched path if the searcher supports it.

    `title_indices`: pass a subset (e.g. [3]) to run only those titles this
    cycle. Used by daemon mode for round-robin rotation.
    `dedup_window_days`: skip URLs already stored within this window. 0 disables.
    """
    queries = build_queries(title_indices=title_indices)
    print(f"  {len(queries)} queries (titles x sites)")

    seen_prior = _load_seen_urls(session, dedup_window_days)
    if seen_prior:
        print(f"  cross-run dedup: skipping URLs from last {dedup_window_days} days ({len(seen_prior)} known)")

    searcher = _get_searcher()
    if getattr(searcher, "supports_batch", False):
        return _search_all_batched(session, run, queries, searcher, seen_prior=seen_prior)

    kept_results: list[SearchResult] = []
    seen: set[str] = set(seen_prior)
    consecutive_empty = 0
    # Aggregate (engine, reason) -> count across the whole run, for end summary.
    engine_failures: dict[tuple[str, str], int] = {}

    for ordinal, (qtext, title_part, site_part, pages_override) in enumerate(queries):
        pages_label = f" (pages={pages_override})" if pages_override else ""
        print(f"  [{ordinal+1}/{len(queries)}]{pages_label} {qtext}")
        sq = SearchQuery(
            run_id=run.id,
            ordinal=ordinal,
            query_text=qtext,
            title_part=title_part,
            site_part=site_part,
        )
        session.add(sq)
        session.flush()  # populate sq.id

        first_page_delay = config.SECONDS_BETWEEN_QUERIES if ordinal > 0 else 0.0
        try:
            raw, unresp = run_query(
                qtext,
                first_page_delay=first_page_delay,
                max_pages=pages_override,
            )
        except Exception as e:
            sq.error = str(e)[:1000]
            session.flush()
            continue

        sq.raw_result_count = len(raw)
        sq.unresponsive_engines = unresp if unresp else None
        # Per-page raw counts for tuning sites.txt pages=N.
        pc: dict[str, int] = {}
        for pageno, _item in raw:
            pc[str(pageno)] = pc.get(str(pageno), 0) + 1
        sq.page_counts = pc or None

        if unresp:
            pretty = ", ".join(f"{name}={reason}" for name, reason in unresp)
            log.warning("    engines unresponsive: %s", pretty)
            for name, reason in unresp:
                engine_failures[(name, reason)] = engine_failures.get((name, reason), 0) + 1

        if not raw:
            consecutive_empty += 1
            if (
                config.COOLOFF_AFTER_EMPTY_QUERIES
                and consecutive_empty >= config.COOLOFF_AFTER_EMPTY_QUERIES
                and ordinal < len(queries) - 1
            ):
                log.warning(
                    "%d consecutive empty queries - cooling off for %.0fs "
                    "(upstream engines likely blocking)",
                    consecutive_empty, config.COOLOFF_SECONDS,
                )
                time.sleep(config.COOLOFF_SECONDS)
                consecutive_empty = 0
        else:
            consecutive_empty = 0

        for pageno, item in raw:
            if not item["url"]:
                continue
            nurl = _normalize_url(item["url"])
            if nurl in seen:
                continue
            seen.add(nurl)
            sr = SearchResult(
                run_id=run.id,
                query_id=sq.id,
                title=item["title"],
                url=item["url"],
                normalized_url=nurl,
                snippet=item["snippet"],
                engine=item["engine"],
                page_no=pageno,
            )
            session.add(sr)
            kept_results.append(sr)

        session.flush()
        # Inter-query spacing is applied by the throttle on the next page-1 fetch.

    print(f"  -> {len(kept_results)} unique results stored")
    if engine_failures:
        print("  Engine issues during this run (engine, reason -> count):")
        for (name, reason), cnt in sorted(
            engine_failures.items(), key=lambda x: x[1], reverse=True
        ):
            print(f"    {name:<14} {reason:<30} {cnt}x")
        captcha_like = sum(
            c for (_n, r), c in engine_failures.items()
            if any(k in r.lower() for k in ("captcha", "too many", "suspended", "blocked"))
        )
        if captcha_like:
            print(
                f"  WARNING: {captcha_like} CAPTCHA/block-style failures detected. "
                "Consider lowering MAX_REQUESTS_PER_MINUTE or waiting before re-running."
            )
    return kept_results


# ---------------------------------------------------------------------------
# Batched pipeline (for searchers with supports_batch = True, e.g. Serper).
# Sends up to `searcher.batch_max` (query, page) items per HTTP call. On batch
# failure, falls back to per-item `fetch_page` so a single bad query can't kill
# the whole chunk.
# ---------------------------------------------------------------------------
def _search_all_batched(
    session: Session,
    run: Run,
    queries: list[tuple[str, str | None, str | None, int | None]],
    searcher: Searcher,
    *,
    seen_prior: set[str] | None = None,
) -> list[SearchResult]:
    # 1. Persist one SearchQuery per logical query so each has an ID.
    sq_objs: list[tuple[SearchQuery, int]] = []
    for ordinal, (qtext, title_part, site_part, pages_override) in enumerate(queries):
        sq = SearchQuery(
            run_id=run.id,
            ordinal=ordinal,
            query_text=qtext,
            title_part=title_part,
            site_part=site_part,
        )
        session.add(sq)
        sq_objs.append((sq, pages_override or config.PAGES_PER_QUERY))
    session.flush()  # populate IDs

    # 2. Expand to (sq, pageno) items, one per HTTP call we'd otherwise make.
    items: list[tuple[SearchQuery, int]] = []
    for sq, pages in sq_objs:
        for pn in range(1, pages + 1):
            items.append((sq, pn))

    batch_max = max(1, getattr(searcher, "batch_max", 1))
    print(
        f"  batched: {len(items)} page requests in "
        f"{(len(items) + batch_max - 1) // batch_max} HTTP call(s) "
        f"(batch_max={batch_max})"
    )

    kept_results: list[SearchResult] = []
    seen: set[str] = set(seen_prior or ())
    sq_counts: dict[int, int] = {sq.id: 0 for sq, _ in sq_objs}
    # Per-(query, page) raw counts for tuning sites.txt pages=N.
    sq_page_counts: dict[int, dict[str, int]] = {sq.id: {} for sq, _ in sq_objs}

    for start in range(0, len(items), batch_max):
        chunk = items[start : start + batch_max]
        payload = [{"q": sq.query_text, "page": pn} for sq, pn in chunk]
        _throttle.acquire(base_delay=config.SECONDS_BETWEEN_QUERIES if start > 0 else 0.0)
        try:
            responses = searcher.fetch_batch(payload)
        except Exception as e:
            log.warning(
                "batch %d-%d failed (%s); falling back to per-item fetch_page",
                start, start + len(chunk), e,
            )
            responses = []
            for sq, pn in chunk:
                try:
                    responses.append(
                        fetch_page(sq.query_text, pn, inter_request_delay=0.0)
                    )
                except Exception as inner:
                    sq.error = (sq.error or "") + f"page {pn}: {inner!s:.200}; "
                    responses.append(([], []))

        for (sq, pn), (results, _diag) in zip(chunk, responses):
            # Record raw count for THIS page before any cap/dedup. JSONB keys
            # must be strings, so stringify the page number.
            sq_page_counts[sq.id][str(pn)] = len(results)
            for item in results:
                if sq_counts[sq.id] >= config.RESULTS_PER_QUERY:
                    break  # Per-query raw cap, mirrors sequential path.
                sq_counts[sq.id] += 1
                if not item["url"]:
                    continue
                nurl = _normalize_url(item["url"])
                if nurl in seen:
                    continue
                seen.add(nurl)
                sr = SearchResult(
                    run_id=run.id,
                    query_id=sq.id,
                    title=item["title"],
                    url=item["url"],
                    normalized_url=nurl,
                    snippet=item["snippet"],
                    engine=item["engine"],
                    page_no=pn,
                )
                session.add(sr)
                kept_results.append(sr)

    for sq, _ in sq_objs:
        sq.raw_result_count = sq_counts[sq.id]
        sq.page_counts = sq_page_counts[sq.id] or None
    session.flush()

    empty_qs = sum(1 for sq, _ in sq_objs if sq_counts[sq.id] == 0)
    print(
        f"  -> {len(kept_results)} unique results stored "
        f"({empty_qs}/{len(sq_objs)} queries returned 0 results)"
    )
    _print_per_site_page_yield(sq_objs, sq_page_counts)
    return kept_results


def _print_per_site_page_yield(
    sq_objs: list[tuple[SearchQuery, int]],
    sq_page_counts: dict[int, dict[str, int]],
) -> None:
    """End-of-run table: avg raw results per page per site. Shows where
    Google's yield drops off, so you can lower `pages=N` in sites.txt.
    """
    # site_part -> page_no (int) -> list[int] of raw counts across titles
    by_site: dict[str, dict[int, list[int]]] = {}
    site_pages: dict[str, int] = {}
    for sq, pages in sq_objs:
        site = sq.site_part or "(no site)"
        site_pages[site] = pages
        bucket = by_site.setdefault(site, {})
        for pn_str, raw in sq_page_counts.get(sq.id, {}).items():
            bucket.setdefault(int(pn_str), []).append(raw)

    if not by_site:
        return
    max_pages = max(site_pages.values())
    print("\n  Per-site page yield (avg raw results across titles):")
    header = f"  {'site':<55}  pages  " + "  ".join(f"p{p}".rjust(5) for p in range(1, max_pages + 1))
    print(header)
    print("  " + "-" * (len(header) - 2))
    for site, page_map in sorted(by_site.items()):
        pages = site_pages[site]
        cells = []
        for p in range(1, max_pages + 1):
            counts = page_map.get(p, [])
            cells.append(f"{sum(counts)/len(counts):5.1f}" if counts else "    -")
        print(f"  {site:<55}  {pages:>5}  " + "  ".join(cells))
