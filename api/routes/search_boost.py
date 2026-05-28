"""Manual paid search routes."""

from __future__ import annotations

import logging
import os
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from threading import Thread
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from api.deps import get_session, require_auth
from api.schemas import (
    SearchSourceExample,
    SearchSourceHost,
    SearchSourceTopQuery,
    SearchSourcesResponse,
    SerperEstimate,
    SerperRunStarted,
)
from db.models import Run, ScoredResult, SearchQuery, SearchResult
from db.session import SessionLocal
from providers.factory import build_provider
from score import score_all
from search import _load_seen_urls, _normalize_url, build_queries
from searchers.base import Searcher
from searchers.factory import build_searcher

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/search",
    tags=["search"],
    dependencies=[Depends(require_auth)],
)


@router.get("/serper/estimate", response_model=SerperEstimate)
def serper_estimate() -> SerperEstimate:
    return _serper_estimate()


@router.post(
    "/serper",
    response_model=SerperRunStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_serper_search(
    session: Session = Depends(get_session),
) -> SerperRunStarted:
    if not os.getenv("SERPER_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="SERPER_API_KEY is not configured",
        )

    running_id = session.scalar(
        select(Run.id).where(Run.status == "running").order_by(Run.started_at.desc())
    )
    if running_id is not None:
        raise HTTPException(
            status_code=409,
            detail=f"run #{running_id} is already running",
        )

    estimate = _serper_estimate()
    run = _new_run()
    session.add(run)
    session.flush()
    session.commit()

    Thread(target=_run_serper_search, args=(run.id,), daemon=True).start()
    return SerperRunStarted(run_id=run.id, **estimate.model_dump())


@router.get("/sources", response_model=SearchSourcesResponse)
def list_sources(
    engine: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = Query(default="result_count_desc"),
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> SearchSourcesResponse:
    """Aggregate SearchResult rows by host, with avg/max score and top
    queries. Use this to find sites that yield poor scores and remove
    them from sites.txt."""
    stmt = (
        select(
            SearchResult.id,
            SearchResult.url,
            SearchResult.engine,
            SearchResult.created_at,
            SearchQuery.query_text,
            ScoredResult.id,
            ScoredResult.score,
            ScoredResult.kept,
        )
        .outerjoin(SearchQuery, SearchResult.query_id == SearchQuery.id)
        .outerjoin(ScoredResult, ScoredResult.search_result_id == SearchResult.id)
    )
    if engine:
        stmt = stmt.where(SearchResult.engine.ilike(f"%{engine}%"))
    if date_from is not None:
        start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        stmt = stmt.where(SearchResult.created_at >= start)
    if date_to is not None:
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        stmt = stmt.where(SearchResult.created_at < end)

    by_host: dict[str, list[dict]] = defaultdict(list)
    for sr_id, url, _engine, _created, query_text, scored_id, score, kept in session.execute(stmt):
        host = (urlparse(url).netloc or "").lower().lstrip("www.")
        if not host:
            continue
        by_host[host].append({
            "sr_id": sr_id,
            "url": url,
            "query_text": query_text,
            "scored_id": scored_id,
            "score": score,
            "kept": bool(kept),
        })

    hosts: list[SearchSourceHost] = []
    for host, rows in by_host.items():
        scores = [r["score"] for r in rows if r["score"] is not None]
        query_counter: Counter[str] = Counter(
            r["query_text"] for r in rows if r["query_text"]
        )
        top_queries = [
            SearchSourceTopQuery(query_text=q, count=n)
            for q, n in query_counter.most_common(3)
        ]
        ranked = sorted(rows, key=lambda r: (r["score"] is not None, r["score"] or -1), reverse=True)
        examples = [
            SearchSourceExample(
                url=r["url"],
                score=r["score"],
                query_text=r["query_text"],
                application_id=r["scored_id"],
            )
            for r in ranked[:3]
        ]
        hosts.append(
            SearchSourceHost(
                host=host,
                result_count=len(rows),
                scored_count=len(scores),
                avg_score=(sum(scores) / len(scores)) if scores else None,
                max_score=max(scores) if scores else None,
                kept_count=sum(1 for r in rows if r["kept"]),
                top_queries=top_queries,
                examples=examples,
            )
        )

    sort_key = {
        "result_count_desc": lambda h: -h.result_count,
        "result_count_asc": lambda h: h.result_count,
        "avg_score_desc": lambda h: -(h.avg_score if h.avg_score is not None else -1),
        "avg_score_asc": lambda h: h.avg_score if h.avg_score is not None else 101,
        "kept_count_desc": lambda h: -h.kept_count,
        "host_asc": lambda h: h.host,
    }.get(sort)
    if sort_key is None:
        raise HTTPException(status_code=422, detail=f"invalid sort: {sort}")
    hosts.sort(key=sort_key)
    return SearchSourcesResponse(total_hosts=len(hosts), hosts=hosts[:limit])


def _serper_estimate() -> SerperEstimate:
    queries = build_queries()
    page_request_count = sum(_page_count(pages_override) for *_, pages_override in queries)
    return SerperEstimate(
        query_count=len(queries),
        page_request_count=page_request_count,
        results_per_query=config.RESULTS_PER_QUERY,
        pages_per_query=config.PAGES_PER_QUERY,
    )


def _page_count(pages_override: int | None) -> int:
    return pages_override if pages_override is not None else config.PAGES_PER_QUERY


def _new_run() -> Run:
    preset = config.PRESETS[config.PROVIDER]
    return Run(
        provider=config.PROVIDER,
        model=str(preset["model"]),
        criteria_text=config.CRITERIA,
        time_range=config.TIME_RANGE,
        location=config.LOCATION,
        results_per_query=config.RESULTS_PER_QUERY,
        batch_size=config.BATCH_SIZE,
        min_score=config.MIN_SCORE,
        status="running",
    )


def _run_serper_search(run_id: int) -> None:
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        if run is None:
            return

        searcher = build_searcher("serper")
        provider = build_provider()
        results = _search_with_serper(session, run, searcher)
        run.total_results = len(results)

        kept = score_all(session, run, results, provider) if results else []
        run.total_kept = len(kept)
        run.status = "succeeded"
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
    except Exception as e:
        log.exception("Serper run #%s failed", run_id)
        session.rollback()
        run = session.get(Run, run_id)
        if run is not None:
            run.status = "failed"
            run.error = str(e)[:2000]
            run.finished_at = datetime.now(timezone.utc)
            session.commit()
    finally:
        session.close()


def _search_with_serper(
    session: Session,
    run: Run,
    searcher: Searcher,
    *,
    dedup_window_days: int = 30,
) -> list[SearchResult]:
    queries = build_queries()
    seen = _load_seen_urls(session, dedup_window_days)

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
        sq_objs.append((sq, _page_count(pages_override)))
    session.flush()

    items: list[tuple[SearchQuery, int]] = []
    for sq, pages in sq_objs:
        for pageno in range(1, pages + 1):
            items.append((sq, pageno))

    kept_results: list[SearchResult] = []
    sq_counts = {sq.id: 0 for sq, _ in sq_objs}
    sq_page_counts: dict[int, dict[str, int]] = {sq.id: {} for sq, _ in sq_objs}
    sq_unresponsive: dict[int, list[list[str]]] = {sq.id: [] for sq, _ in sq_objs}
    batch_max = max(1, getattr(searcher, "batch_max", 1))

    for start in range(0, len(items), batch_max):
        chunk = items[start : start + batch_max]
        payload = [{"q": sq.query_text, "page": page_no} for sq, page_no in chunk]
        responses = _fetch_serper_chunk(searcher, chunk, payload)

        for (sq, page_no), (results, diagnostics) in zip(chunk, responses):
            sq_page_counts[sq.id][str(page_no)] = len(results)
            if diagnostics:
                sq_unresponsive[sq.id].extend(diagnostics)

            for item in results:
                if sq_counts[sq.id] >= config.RESULTS_PER_QUERY:
                    break
                sq_counts[sq.id] += 1
                url = str(item.get("url") or "")
                if not url:
                    continue
                normalized_url = _normalize_url(url)
                if normalized_url in seen:
                    continue
                seen.add(normalized_url)
                result = SearchResult(
                    run_id=run.id,
                    query_id=sq.id,
                    title=str(item.get("title") or ""),
                    url=url,
                    normalized_url=normalized_url,
                    snippet=str(item.get("snippet") or ""),
                    engine=str(item.get("engine") or "google (serper)"),
                    page_no=page_no,
                )
                session.add(result)
                kept_results.append(result)

    for sq, _ in sq_objs:
        sq.raw_result_count = sq_counts[sq.id]
        sq.page_counts = sq_page_counts[sq.id] or None
        sq.unresponsive_engines = sq_unresponsive[sq.id] or None
    session.flush()
    return kept_results


def _fetch_serper_chunk(
    searcher: Searcher,
    chunk: list[tuple[SearchQuery, int]],
    payload: list[dict[str, object]],
) -> list[tuple[list[dict], list[list[str]]]]:
    try:
        return searcher.fetch_batch(payload)
    except Exception as e:
        log.warning("Serper batch failed; falling back to per-page fetch: %s", e)

    responses: list[tuple[list[dict], list[list[str]]]] = []
    for sq, page_no in chunk:
        try:
            responses.append(searcher.fetch_page(sq.query_text, page_no))
        except Exception as inner:
            sq.error = (sq.error or "") + f"page {page_no}: {inner!s:.200}; "
            responses.append(([], [["serper", str(inner)[:200]]]))
    return responses
