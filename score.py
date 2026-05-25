"""Batch search results through the LLM, persist every call, filter + sort."""

from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy.orm import Session

import config
from db.models import LLMCall, Run, ScoredResult, SearchResult
from providers.base import LLMProvider

log = logging.getLogger(__name__)


def _chunks(seq: list[SearchResult], size: int) -> Iterable[list[SearchResult]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _to_dict(sr: SearchResult) -> dict:
    return {
        "title": sr.title,
        "url": sr.url,
        "snippet": sr.snippet,
        "engine": sr.engine,
    }


def score_all(
    session: Session,
    run: Run,
    search_results: list[SearchResult],
    provider: LLMProvider,
    *,
    criteria: str | None = None,
    batch_size: int | None = None,
    min_score: int | None = None,
) -> list[ScoredResult]:
    """Score every result. Persists each LLM call + each ScoredResult."""
    criteria = criteria if criteria is not None else config.CRITERIA
    batch_size = batch_size or config.BATCH_SIZE
    min_score = min_score if min_score is not None else config.MIN_SCORE

    total_batches = (len(search_results) + batch_size - 1) // batch_size
    all_scored: list[ScoredResult] = []

    for bi, batch in enumerate(_chunks(search_results, batch_size)):
        print(f"  scoring batch {bi+1}/{total_batches} ({len(batch)} items)")
        try:
            outcome = provider.score_batch([_to_dict(sr) for sr in batch], criteria)
        except Exception as e:
            log.warning("batch %d crashed entirely: %s", bi + 1, e)
            continue

        # Persist every LLM call we made for this batch.
        last_call: LLMCall | None = None
        for rec in outcome.calls:
            llm_call = LLMCall(
                run_id=run.id,
                batch_index=bi,
                provider=outcome.provider or provider.provider_name,
                model=outcome.model or provider.model,
                mode=rec.mode,
                attempt=rec.attempt,
                system_prompt=rec.system_prompt,
                user_prompt=rec.user_prompt,
                raw_response=rec.raw_response,
                parsed_ok=rec.parsed_ok,
                latency_ms=rec.latency_ms,
                error=rec.error,
            )
            session.add(llm_call)
            session.flush()
            if rec.parsed_ok:
                last_call = llm_call

        # If nothing parsed, skip persisting scored rows for this batch.
        if last_call is None or not outcome.scored:
            continue

        for sj in outcome.scored:
            if sj.index < 0 or sj.index >= len(batch):
                continue
            sr = batch[sj.index]
            kept = bool(sj.is_job and sj.score >= min_score)
            scored = ScoredResult(
                run_id=run.id,
                search_result_id=sr.id,
                llm_call_id=last_call.id,
                is_job=sj.is_job,
                title=sj.title,
                company=sj.company,
                location=sj.location,
                remote=sj.remote,
                score=sj.score,
                reason=sj.reason,
                kept=kept,
            )
            session.add(scored)
            all_scored.append(scored)

        session.flush()

    kept_list = [s for s in all_scored if s.kept]
    kept_list.sort(key=lambda s: s.score, reverse=True)
    print(f"  -> kept {len(kept_list)}/{len(all_scored)} (min_score={min_score})")
    return kept_list
