"""End-to-end orchestrator: search -> dedup -> score -> DB + CSV + markdown.

Daemon mode: `python main.py --daemon` runs the pipeline every
`--interval` minutes (default 30), rotating one title per run so each
cycle spreads load across the day and avoids SearXNG/Google CAPTCHA.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy.orm import Session

import config
from db.bootstrap import init_db
from db.models import Run, ScoredResult, SearchResult
from db.session import SessionLocal
from notifications import notify_unsent_jobs
from providers.factory import build_provider
from score import score_all
from search import load_titles, search_all


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _row_for(s: ScoredResult, sr_by_id: dict[int, SearchResult]) -> dict:
    src = sr_by_id.get(s.search_result_id)
    return {
        "score": s.score,
        "title": s.title,
        "company": s.company,
        "location": s.location,
        "remote": s.remote,
        "url": src.url if src else "",
        "reason": s.reason,
        "search_title": src.title if src else "",
        "snippet": src.snippet if src else "",
        "engine": src.engine if src else "",
    }


def _write_csv(rows: list[dict], path: str) -> None:
    fields = [
        "score", "title", "company", "location", "remote", "url",
        "reason", "engine", "search_title", "snippet",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def _write_digest(rows: list[dict], path: str, *, run: Run) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Job digest - run #{run.id} - {ts}",
        "",
        f"- provider: `{run.provider}` model: `{run.model}`",
        f"- time_range: `{run.time_range}` location: `{run.location}`",
        f"- kept: **{len(rows)}** results (score >= {run.min_score})",
        "",
    ]
    for r in rows:
        loc = r.get("location") or ""
        if r.get("remote"):
            loc = (loc + " (remote)").strip()
        title = r.get("title") or r.get("search_title") or "(untitled)"
        lines.append(f"## [{title}]({r['url']}) - score {r['score']}")
        meta = " - ".join(x for x in [r.get("company", ""), loc] if x)
        if meta:
            lines.append(f"*{meta}*")
        if r.get("reason"):
            lines.append("")
            lines.append(f"> {r['reason']}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _run_pipeline(
    session: Session,
    *,
    title_indices: list[int] | None = None,
    dedup_window_days: int = 30,
) -> int:
    print(f"Search backend: {config.SEARCH_BACKEND}")
    print(f"LLM provider:   {config.PROVIDER}")
    if title_indices is not None:
        titles = load_titles()
        active = [titles[i] for i in title_indices if 0 <= i < len(titles)]
        print(f"Title subset:   {active}")
    provider = build_provider()
    preset = config.PRESETS[config.PROVIDER]

    run = Run(
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
    session.add(run)
    session.flush()
    print(f"Started run #{run.id}")

    try:
        print(f"Running searches against {config.SEARCH_BACKEND}...")
        results = search_all(
            session,
            run,
            title_indices=title_indices,
            dedup_window_days=dedup_window_days,
        )
        run.total_results = len(results)
        session.flush()

        if not results:
            # Could be a real failure OR everything was already deduped from
            # prior runs - both are normal in daemon mode. Mark succeeded.
            print("No new search results this cycle.")
            run.status = "succeeded"
            run.finished_at = datetime.now(timezone.utc)
            return 0

        print(f"Scoring {len(results)} results with {config.PROVIDER}...")
        kept = score_all(session, run, results, provider)
        run.total_kept = len(kept)
        run.status = "succeeded"
        run.finished_at = datetime.now(timezone.utc)
        session.flush()

        sr_by_id = {sr.id: sr for sr in results}
        rows = [_row_for(s, sr_by_id) for s in kept]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        csv_path = os.path.join(config.OUTPUT_DIR, f"jobs_{stamp}_run{run.id}.csv")
        md_path = os.path.join(config.OUTPUT_DIR, f"digest_{stamp}_run{run.id}.md")
        _write_csv(rows, csv_path)
        _write_digest(rows, md_path, run=run)
        print(f"Wrote {csv_path}")
        print(f"Wrote {md_path}")
        return 0
    except Exception as e:
        logging.exception("run #%s failed", run.id)
        run.status = "failed"
        run.error = str(e)[:2000]
        run.finished_at = datetime.now(timezone.utc)
        session.flush()
        return 2


def _run_once(
    title_indices: list[int] | None,
    dedup_window_days: int,
    *,
    send_email: bool,
) -> int:
    session = SessionLocal()
    try:
        rc = _run_pipeline(
            session,
            title_indices=title_indices,
            dedup_window_days=dedup_window_days,
        )
        session.commit()
        if rc == 0 and send_email:
            try:
                notify_unsent_jobs(session)
                session.commit()
            except Exception as e:
                session.rollback()
                logging.exception("email notification failed: %s", e)
        return rc
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _notify_only() -> int:
    session = SessionLocal()
    try:
        notify_unsent_jobs(session)
        session.commit()
        return 0
    except Exception as e:
        session.rollback()
        logging.exception("email notification failed: %s", e)
        return 2
    finally:
        session.close()


def _wait_for_engine(engine: str, poll_minutes: int) -> bool:
    """Poll SearXNG every `poll_minutes` until `engine` clears its block.
    Returns True when healthy, False on Ctrl-C."""
    url = f"{config.SEARXNG_URL.rstrip('/')}/search"
    print(
        f"Waiting for SearXNG engine {engine!r} to clear "
        f"(probe every {poll_minutes}min; Ctrl-C to abort)..."
    )
    attempt = 0
    while True:
        attempt += 1
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            r = requests.get(
                url, params={"q": "test", "format": "json"}, timeout=20
            )
            r.raise_for_status()
            unresp = r.json().get("unresponsive_engines") or []
            blocked = [u for u in unresp if u and u[0] == engine]
            if not blocked:
                print(f"[{ts}] attempt {attempt}: {engine!r} healthy. Starting daemon.")
                return True
            reason = blocked[0][1] if len(blocked[0]) > 1 else "unknown"
            print(f"[{ts}] attempt {attempt}: {engine!r} still blocked ({reason}). Sleeping {poll_minutes}min.")
        except Exception as e:
            print(f"[{ts}] attempt {attempt}: probe failed ({e}). Sleeping {poll_minutes}min.")
        try:
            time.sleep(poll_minutes * 60)
        except KeyboardInterrupt:
            print("\nInterrupted while waiting - exiting.")
            return False


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--daemon", action="store_true",
        help="Loop forever, sleeping --interval minutes between runs.",
    )
    p.add_argument(
        "--interval", type=int, default=30,
        help="Minutes between daemon runs (default: 30).",
    )
    p.add_argument(
        "--full-each-run", action="store_true",
        help="In daemon mode, do all titles every run instead of rotating one per run.",
    )
    p.add_argument(
        "--dedup-window-days", type=int, default=30,
        help="Skip URLs already seen within this many days (0 disables; default: 30).",
    )
    p.add_argument(
        "--wait-for-engine", metavar="NAME", default=None,
        help="Before starting, poll SearXNG until NAME (e.g. 'google') is not in "
             "unresponsive_engines. Useful after a CAPTCHA event.",
    )
    p.add_argument(
        "--wait-poll-minutes", type=int, default=15,
        help="Minutes between probes when --wait-for-engine is set (default: 15).",
    )
    p.add_argument(
        "--notify-only", action="store_true",
        help="Send the email digest for already-scored unsent jobs, then exit.",
    )
    p.add_argument(
        "--skip-email", action="store_true",
        help="Run search/scoring without sending the email digest.",
    )
    return p.parse_args()


def main() -> int:
    # Line-buffer stdout/stderr so background runs (no TTY) flush prints
    # immediately instead of waiting for a 4KB block buffer to fill.
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    args = _parse_args()
    _setup_logging()
    init_db()

    if args.notify_only:
        return _notify_only()

    if args.wait_for_engine:
        if not _wait_for_engine(args.wait_for_engine, args.wait_poll_minutes):
            return 0

    if not args.daemon:
        return _run_once(
            title_indices=None,
            dedup_window_days=args.dedup_window_days,
            send_email=not args.skip_email,
        )

    titles = load_titles()
    if not titles:
        print("No titles found in titles.txt - cannot run daemon mode.")
        return 1
    n_titles = len(titles)
    interval_s = max(60, args.interval * 60)
    print(
        f"Daemon mode: {n_titles} titles, interval={args.interval}min, "
        f"rotation={'off (full sweep)' if args.full_each_run else f'on (1/{n_titles} per run)'}"
    )

    cycle = 0
    while True:
        if args.full_each_run:
            title_indices = None
            label = f"cycle {cycle} (all titles)"
        else:
            idx = cycle % n_titles
            title_indices = [idx]
            label = f"cycle {cycle} title #{idx}: {titles[idx]!r}"
        print(f"\n{'='*70}\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {label}\n{'='*70}")
        try:
            _run_once(
                title_indices,
                args.dedup_window_days,
                send_email=not args.skip_email,
            )
        except KeyboardInterrupt:
            print("\nInterrupted - exiting daemon.")
            return 0
        except Exception as e:
            logging.exception("daemon iteration failed: %s", e)
            # Don't crash the daemon on one bad run.
        cycle += 1
        wake_at = datetime.now() + timedelta(seconds=interval_s)
        print(f"Sleeping {args.interval}min - next run ~{wake_at.strftime('%H:%M:%S')}. Ctrl-C to stop.")
        try:
            time.sleep(interval_s)
        except KeyboardInterrupt:
            print("\nInterrupted - exiting daemon.")
            return 0


if __name__ == "__main__":
    sys.exit(main())
