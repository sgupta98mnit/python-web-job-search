"""Threadpooled, cached JD fetcher. The single entry point used by score.py.

Concurrency: a ThreadPoolExecutor of JD_FETCH_WORKERS workers issues GETs;
a HostTokenBucket serializes requests to the same host at JD_FETCH_PER_HOST_RPS.

Caching: rows in `job_descriptions` are reused when fetched_at is within
JD_CACHE_TTL_DAYS. Both successes and failures are cached this way -- a
failure row prevents an immediate retry but expires normally, so a future
run can pick it up again.
"""

from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from db.models import JobDescription
from fetcher.base import FetchOutcome
from fetcher.extractors.registry import ats_for_host, extractors_for_host
from fetcher.throttle import HostTokenBucket

log = logging.getLogger(__name__)

# Single shared bucket per process is fine -- the rate is per-host, not global.
_bucket = HostTokenBucket(rps=config.JD_FETCH_PER_HOST_RPS)
_http_session = requests.Session()


def fetch_many(
    session: Session,
    urls: list[tuple[str, str]],
) -> dict[str, FetchOutcome]:
    """Fetch (or look up cached) bodies for every (normalized_url, url).

    Returns: {normalized_url: FetchOutcome}. Every key in `urls` is in
    the result. Cache hits return immediately; misses are fanned across
    a threadpool.
    """
    if not urls:
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=config.JD_CACHE_TTL_DAYS)
    nurl_set = [nurl for nurl, _ in urls]

    cached_rows: dict[str, JobDescription] = {
        row.normalized_url: row
        for row in session.scalars(
            select(JobDescription)
            .where(JobDescription.normalized_url.in_(nurl_set))
            .where(JobDescription.fetched_at >= cutoff)
        )
    }

    outcomes: dict[str, FetchOutcome] = {}
    misses: list[tuple[str, str]] = []
    for nurl, url in urls:
        row = cached_rows.get(nurl)
        if row is not None:
            outcomes[nurl] = _outcome_from_row(row)
        else:
            misses.append((nurl, url))

    if not misses:
        return outcomes

    workers = max(1, min(config.JD_FETCH_WORKERS, len(misses)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_one, url): (nurl, url) for nurl, url in misses
        }
        for fut in futures:
            nurl, url = futures[fut]
            outcome = fut.result()
            # Persist (insert or update) on the calling thread so we hold one
            # session/transaction. SQLAlchemy sessions are not thread-safe.
            row = _upsert(session, nurl=nurl, url=url, outcome=outcome)
            outcomes[nurl] = replace(outcome, job_description_id=row.id)
    session.flush()
    return outcomes


def _outcome_from_row(row: JobDescription) -> FetchOutcome:
    return FetchOutcome(
        status=row.status,  # type: ignore[arg-type]
        ats=row.ats or "generic",
        body_text=row.body_text,
        http_status=row.http_status,
        error=row.error,
        latency_ms=row.latency_ms or 0,
        extractor=row.extractor,
        job_description_id=row.id,
    )


def _fetch_one(url: str) -> FetchOutcome:
    host = (urlparse(url).netloc or "").lower()
    ats = ats_for_host(host)
    _bucket.acquire(host)

    start = time.monotonic()
    try:
        resp = _http_session.get(
            url,
            timeout=config.JD_FETCH_TIMEOUT,
            headers={"User-Agent": config.JD_USER_AGENT},
            allow_redirects=True,
        )
    except requests.Timeout as e:
        return FetchOutcome(
            status="timeout", ats=ats, body_text=None, http_status=None,
            error=str(e)[:1000], latency_ms=int((time.monotonic() - start) * 1000),
            extractor="(none)", job_description_id=None,
        )
    except requests.RequestException as e:
        return FetchOutcome(
            status="http_error", ats=ats, body_text=None, http_status=None,
            error=str(e)[:1000], latency_ms=int((time.monotonic() - start) * 1000),
            extractor="(none)", job_description_id=None,
        )

    latency_ms = int((time.monotonic() - start) * 1000)

    if resp.status_code >= 400:
        return FetchOutcome(
            status="http_error", ats=ats, body_text=None,
            http_status=resp.status_code,
            error=f"HTTP {resp.status_code}", latency_ms=latency_ms,
            extractor="(none)", job_description_id=None,
        )

    ct = (resp.headers.get("Content-Type") or "").lower()
    if ct and "html" not in ct and "xml" not in ct:
        return FetchOutcome(
            status="unsupported", ats=ats, body_text=None,
            http_status=resp.status_code,
            error=f"non-HTML content-type: {ct}", latency_ms=latency_ms,
            extractor="(none)", job_description_id=None,
        )

    html = resp.text or ""
    body: str | None = None
    extractor_name = "(none)"
    for extractor in extractors_for_host(host):
        try:
            result = extractor.extract(url=url, html=html)
        except Exception as e:
            log.warning("extractor %s crashed on %s: %s", extractor.name, url, e)
            continue
        if result.body_text:
            body = result.body_text
            extractor_name = result.extractor
            break
        extractor_name = result.extractor  # remember the last one we tried

    if body is None:
        return FetchOutcome(
            status="parse_failed", ats=ats, body_text=None,
            http_status=resp.status_code,
            error="no extractor returned body_text", latency_ms=latency_ms,
            extractor=extractor_name, job_description_id=None,
        )

    if len(body) < config.JD_MIN_BODY_CHARS:
        return FetchOutcome(
            status="unsupported", ats=ats, body_text=None,
            http_status=resp.status_code,
            error=f"body shorter than {config.JD_MIN_BODY_CHARS} chars ({len(body)})",
            latency_ms=latency_ms,
            extractor=extractor_name, job_description_id=None,
        )

    return FetchOutcome(
        status="ok", ats=ats, body_text=body,
        http_status=resp.status_code,
        error=None, latency_ms=latency_ms,
        extractor=extractor_name, job_description_id=None,
    )


def _upsert(
    session: Session, *, nurl: str, url: str, outcome: FetchOutcome
) -> JobDescription:
    row = session.scalar(
        select(JobDescription).where(JobDescription.normalized_url == nurl)
    )
    sha = (
        hashlib.sha256(outcome.body_text.encode("utf-8")).hexdigest()
        if outcome.body_text
        else None
    )
    if row is None:
        row = JobDescription(
            normalized_url=nurl,
            url=url,
            status=outcome.status,
            http_status=outcome.http_status,
            ats=outcome.ats,
            body_text=outcome.body_text,
            body_html_sha256=sha,
            extractor=outcome.extractor,
            error=outcome.error,
            latency_ms=outcome.latency_ms,
            fetched_at=datetime.now(timezone.utc),
        )
        session.add(row)
    else:
        row.url = url
        row.status = outcome.status
        row.http_status = outcome.http_status
        row.ats = outcome.ats
        row.body_text = outcome.body_text
        row.body_html_sha256 = sha
        row.extractor = outcome.extractor
        row.error = outcome.error
        row.latency_ms = outcome.latency_ms
        row.fetched_at = datetime.now(timezone.utc)
    session.flush()
    return row
