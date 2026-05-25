"""Manual paid search routes."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from threading import Thread

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from api.deps import get_session, require_auth
from api.schemas import SerperEstimate, SerperRunStarted
from db.models import Run, SearchQuery, SearchResult
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
