"""Batch search results through the LLM, persist every call, filter + sort."""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

import config
import fetcher
from db.events import record_event
from db.models import LLMCall, Run, ScoredResult, SearchResult
from providers.base import LLMProvider
from score_filters import auto_reject_reason

log = logging.getLogger(__name__)


def _chunks(seq: list[SearchResult], size: int) -> Iterable[list[SearchResult]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _pick_description(sr: SearchResult, outcome) -> tuple[str, str, int | None]:
    """Return (description_text, source, job_description_id). When the
    fetched body is available, use it; otherwise fall back to the snippet."""
    if outcome is not None and outcome.status == "ok" and outcome.body_text:
        return outcome.body_text, "body", outcome.job_description_id
    return sr.snippet, "snippet_fallback" if outcome is not None else "snippet", None


def _to_dict(sr: SearchResult, outcome=None) -> dict:
    description, _source, _jd_id = _pick_description(sr, outcome)
    return {
        "title": sr.title,
        "url": sr.url,
        "snippet": description,  # field name kept for prompt compatibility
        "engine": sr.engine,
    }


def _copy_score(
    *,
    run: Run,
    search_result_id: int,
    llm_call_id: int,
    source: ScoredResult,
    min_score: int,
) -> ScoredResult:
    kept = bool(source.is_job and source.score >= min_score)
    rejection_tags: str | None = source.rejection_reason
    if config.AUTO_REJECT_ENABLED and rejection_tags is None:
        # Re-evaluate in case the source predates auto-rejection.
        rejection_tags = auto_reject_reason(
            is_job=source.is_job,
            score=source.score,
            location=source.location,
            remote=source.remote,
            min_score=config.AUTO_REJECT_MIN_SCORE,
            enforce_usa=config.AUTO_REJECT_REQUIRE_USA,
        )
    if rejection_tags:
        kept = False
    return ScoredResult(
        run_id=run.id,
        search_result_id=search_result_id,
        llm_call_id=llm_call_id,
        is_job=source.is_job,
        title=source.title,
        company=source.company,
        location=source.location,
        remote=source.remote,
        score=source.score,
        reason=f"{source.reason} (reused cached score)".strip(),
        kept=kept,
        rejection_reason=rejection_tags,
    )


def _cached_scores(
    session: Session,
    run: Run,
    search_results: list[SearchResult],
    *,
    criteria: str,
) -> dict[int, ScoredResult]:
    if not search_results:
        return {}

    urls = {sr.normalized_url for sr in search_results}
    stmt = (
        select(SearchResult.normalized_url, ScoredResult)
        .join(ScoredResult, ScoredResult.search_result_id == SearchResult.id)
        .join(Run, Run.id == ScoredResult.run_id)
        .where(SearchResult.normalized_url.in_(urls))
        .where(Run.provider == run.provider)
        .where(Run.model == run.model)
        .where(Run.criteria_text == criteria)
        .where(Run.id != run.id)
        .order_by(ScoredResult.created_at.desc(), ScoredResult.id.desc())
    )
    by_url: dict[str, ScoredResult] = {}
    for normalized_url, scored in session.execute(stmt):
        by_url.setdefault(normalized_url, scored)
    return {
        sr.id: by_url[sr.normalized_url]
        for sr in search_results
        if sr.normalized_url in by_url
    }


def _new_audit_call(
    session: Session,
    run: Run,
    *,
    batch_index: int,
    provider: str,
    model: str,
    mode: str,
    system_prompt: str,
    user_prompt: str,
    raw_response: dict,
) -> LLMCall:
    call = LLMCall(
        run_id=run.id,
        batch_index=batch_index,
        provider=provider,
        model=model,
        mode=mode,
        attempt=1,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        raw_response=raw_response,
        parsed_ok=True,
        latency_ms=0,
        error=None,
    )
    session.add(call)
    session.flush()
    return call


def _prefilter_reason(sr: SearchResult) -> str | None:
    text = f"{sr.title} {sr.snippet}".lower()
    url = sr.url.lower()
    path = urlparse(sr.url).path.lower()

    non_job_domains = (
        "indeed.com",
        "linkedin.com",
        "ziprecruiter.com",
        "glassdoor.com",
        "builtin.com",
    )
    if any(domain in url for domain in non_job_domains):
        return "filtered before LLM: aggregator/search result domain"

    non_job_path_bits = (
        "/blog",
        "/blogs",
        "/career-advice",
        "/companies",
        "/company/",
        "/reviews",
        "/salaries",
        "/search",
    )
    if any(bit in path for bit in non_job_path_bits):
        return "filtered before LLM: non-job path"

    non_job_phrases = (
        "job search",
        "jobs and salaries",
        "salary guide",
        "career advice",
        "best companies",
        "interview questions",
    )
    if any(phrase in text for phrase in non_job_phrases):
        return "filtered before LLM: non-job page text"

    return None


def _prefiltered_score(
    *,
    run: Run,
    search_result_id: int,
    llm_call_id: int,
    sr: SearchResult,
    reason: str,
) -> ScoredResult:
    return ScoredResult(
        run_id=run.id,
        search_result_id=search_result_id,
        llm_call_id=llm_call_id,
        is_job=False,
        title=sr.title,
        company="",
        location="",
        remote=False,
        score=0,
        reason=reason,
        kept=False,
    )


def score_all(
    session: Session,
    run: Run,
    search_results: list[SearchResult],
    provider: LLMProvider,
    *,
    criteria: str | None = None,
    batch_size: int | None = None,
    min_score: int | None = None,
    commit_each_batch: bool = False,
) -> list[ScoredResult]:
    """Score every result. Persists each LLM call + each ScoredResult."""
    criteria = criteria if criteria is not None else config.CRITERIA
    batch_size = batch_size or config.BATCH_SIZE
    min_score = min_score if min_score is not None else config.MIN_SCORE

    total_batches = (len(search_results) + batch_size - 1) // batch_size
    all_scored: list[ScoredResult] = []
    cache_hits = 0
    prefilter_hits = 0
    llm_scored = 0

    jd_totals = {
        "fetched": 0,
        "cached": 0,
        "ok": 0,
        "http_error": 0,
        "timeout": 0,
        "unsupported": 0,
        "parse_failed": 0,
        "snippet_fallback": 0,
        "jina_recovered": 0,
    }
    jd_ats: dict[str, int] = {}

    for bi, batch in enumerate(_chunks(search_results, batch_size)):
        print(f"  scoring batch {bi+1}/{total_batches} ({len(batch)} items)")
        to_score = list(batch)

        if config.SCORE_CACHE_ENABLED:
            cached = _cached_scores(session, run, to_score, criteria=criteria)
            if cached:
                call = _new_audit_call(
                    session,
                    run,
                    batch_index=bi,
                    provider=provider.provider_name,
                    model=provider.model,
                    mode="score_cache",
                    system_prompt="score cache",
                    user_prompt=f"Reused {len(cached)} prior scores by normalized URL.",
                    raw_response={"cached_count": len(cached)},
                )
                remaining: list[SearchResult] = []
                for sr in to_score:
                    source = cached.get(sr.id)
                    if source is None:
                        remaining.append(sr)
                        continue
                    scored = _copy_score(
                        run=run,
                        search_result_id=sr.id,
                        llm_call_id=call.id,
                        source=source,
                        min_score=min_score,
                    )
                    session.add(scored)
                    all_scored.append(scored)
                    cache_hits += 1
                    record_event(
                        session,
                        normalized_url=sr.normalized_url,
                        run_id=run.id,
                        stage="score_cache_hit",
                        message=f"reused prior score={source.score} from llm_call_id={source.llm_call_id}",
                        details={
                            "score": source.score,
                            "kept": scored.kept,
                            "prior_llm_call_id": source.llm_call_id,
                        },
                    )
                to_score = remaining

        if config.SCORE_PREFILTER_ENABLED:
            prefetched = [(sr, _prefilter_reason(sr)) for sr in to_score]
            filtered = [(sr, reason) for sr, reason in prefetched if reason]
            if filtered:
                call = _new_audit_call(
                    session,
                    run,
                    batch_index=bi,
                    provider=provider.provider_name,
                    model=provider.model,
                    mode="heuristic_prefilter",
                    system_prompt="heuristic prefilter",
                    user_prompt=f"Filtered {len(filtered)} obvious non-job results before LLM.",
                    raw_response={"filtered_count": len(filtered)},
                )
                filtered_ids = {sr.id for sr, _ in filtered}
                for sr, reason in filtered:
                    scored = _prefiltered_score(
                        run=run,
                        search_result_id=sr.id,
                        llm_call_id=call.id,
                        sr=sr,
                        reason=str(reason),
                    )
                    session.add(scored)
                    all_scored.append(scored)
                    prefilter_hits += 1
                    record_event(
                        session,
                        normalized_url=sr.normalized_url,
                        run_id=run.id,
                        stage="prefiltered",
                        message=f"prefiltered: {reason}",
                        details={"reason": str(reason)},
                    )
                to_score = [sr for sr in to_score if sr.id not in filtered_ids]

        if not to_score:
            session.flush()
            if commit_each_batch:
                session.commit()
            print("    skipped LLM: all items handled by cache/prefilter")
            continue

        if config.JD_FETCH_ENABLED:
            jd_outcomes = fetcher.fetch_many(
                session,
                [(sr.normalized_url, sr.url) for sr in to_score],
                run_id=run.id,
            )
        else:
            jd_outcomes = {}

        for _nurl, oc in jd_outcomes.items():
            # We can't distinguish 'cached' from 'fresh' purely from the
            # outcome, so we count by status; the cache-vs-fresh split is
            # observable in job_descriptions.fetched_at directly.
            jd_totals[oc.status] = jd_totals.get(oc.status, 0) + 1
            jd_totals["fetched"] += 1
            if oc.status == "ok":
                jd_ats[oc.ats] = jd_ats.get(oc.ats, 0) + 1
                if oc.extractor == "jina_reader":
                    jd_totals["jina_recovered"] += 1
            else:
                jd_totals["snippet_fallback"] += 1

        prepared = [
            (sr, _pick_description(sr, jd_outcomes.get(sr.normalized_url)))
            for sr in to_score
        ]
        payloads = [_to_dict(sr, jd_outcomes.get(sr.normalized_url)) for sr in to_score]

        try:
            outcome = provider.score_batch(payloads, criteria)
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
            if sj.index < 0 or sj.index >= len(to_score):
                continue
            sr = to_score[sj.index]
            kept = bool(sj.is_job and sj.score >= min_score)
            _sr, (_desc, source, jd_id) = prepared[sj.index]
            rejection_tags: str | None = None
            if config.AUTO_REJECT_ENABLED:
                rejection_tags = auto_reject_reason(
                    is_job=sj.is_job,
                    score=sj.score,
                    location=sj.location,
                    remote=sj.remote,
                    min_score=config.AUTO_REJECT_MIN_SCORE,
                    enforce_usa=config.AUTO_REJECT_REQUIRE_USA,
                )
            if rejection_tags:
                kept = False
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
                source=source,
                job_description_id=jd_id,
                rejection_reason=rejection_tags,
            )
            session.add(scored)
            all_scored.append(scored)
            llm_scored += 1
            record_event(
                session,
                normalized_url=sr.normalized_url,
                run_id=run.id,
                stage="llm_scored",
                message=f"score={sj.score} kept={kept} location={sj.location!r}",
                details={
                    "score": sj.score,
                    "is_job": sj.is_job,
                    "kept": kept,
                    "title": sj.title,
                    "company": sj.company,
                    "location": sj.location,
                    "remote": sj.remote,
                    "source": source,
                    "llm_call_id": last_call.id,
                    "job_description_id": jd_id,
                    "reason": sj.reason,
                    "rejection_reason": rejection_tags,
                },
            )
            if rejection_tags:
                record_event(
                    session,
                    normalized_url=sr.normalized_url,
                    run_id=run.id,
                    stage="auto_rejected",
                    message=f"auto-rejected: {rejection_tags}",
                    details={
                        "tags": rejection_tags.split(","),
                        "score": sj.score,
                        "location": sj.location,
                        "remote": sj.remote,
                    },
                )

        session.flush()
        if commit_each_batch:
            session.commit()

    kept_list = [s for s in all_scored if s.kept]
    kept_list.sort(key=lambda s: s.score, reverse=True)
    print(f"  -> kept {len(kept_list)}/{len(all_scored)} (min_score={min_score})")
    if cache_hits or prefilter_hits:
        print(
            "  cost controls: "
            f"cache_hits={cache_hits}, prefiltered={prefilter_hits}, "
            f"llm_scored={llm_scored}"
        )
    if jd_totals["fetched"]:
        ats_summary = ", ".join(
            f"{ats}={n}" for ats, n in sorted(jd_ats.items(), key=lambda x: -x[1])
        ) or "(none)"
        print(
            "  JD fetch: "
            f"fetched={jd_totals['fetched']} "
            f"ok={jd_totals['ok']} "
            f"http_error={jd_totals['http_error']} "
            f"timeout={jd_totals['timeout']} "
            f"unsupported={jd_totals['unsupported']} "
            f"parse_failed={jd_totals['parse_failed']} "
            f"snippet_fallback={jd_totals['snippet_fallback']} "
            f"jina_recovered={jd_totals['jina_recovered']}"
        )
        print(f"  ATS mix (ok-only): {ats_summary}")
    return kept_list
