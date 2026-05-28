"""One-shot backfill: tag existing ScoredResult rows that the new
deterministic filter would auto-reject.

Idempotent: rerunning sets the same tags and produces the same counts.
Run after deploying the `rejection_reason` column.

    python -m scripts.backfill_rejections
"""

from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy import select

import config
from db.models import ScoredResult
from db.session import session_scope
from score_filters import auto_reject_reason

log = logging.getLogger(__name__)


def main() -> int:
    counters: Counter[str] = Counter()
    cleared = 0
    changed = 0
    unchanged = 0

    with session_scope() as session:
        rows = list(session.scalars(select(ScoredResult)))
        for row in rows:
            new_tags = auto_reject_reason(
                is_job=row.is_job,
                score=row.score,
                location=row.location,
                remote=row.remote,
                min_score=config.AUTO_REJECT_MIN_SCORE,
                enforce_usa=config.AUTO_REJECT_REQUIRE_USA,
            )
            if new_tags == row.rejection_reason:
                unchanged += 1
                if new_tags:
                    for tag in new_tags.split(","):
                        counters[tag] += 1
                continue

            if new_tags:
                row.rejection_reason = new_tags
                row.kept = False
                changed += 1
                for tag in new_tags.split(","):
                    counters[tag] += 1
            elif row.rejection_reason is not None:
                # Filter is now lenient enough that this row no longer matches.
                row.rejection_reason = None
                cleared += 1

    total = len(rows)
    print(f"scanned: {total}")
    print(f"newly tagged: {changed}")
    print(f"already tagged (unchanged): {unchanged}")
    print(f"cleared: {cleared}")
    if counters:
        print("tag counts (after backfill):")
        for tag, count in counters.most_common():
            print(f"  {tag}: {count}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
