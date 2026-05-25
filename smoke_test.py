"""Provider-layer smoke test. Runs WITHOUT SearXNG.

Usage:
    python smoke_test.py          # uses config.PROVIDER (defaults to ollama)
    python smoke_test.py openai   # override provider on the command line
"""

from __future__ import annotations

import logging
import sys

from providers.factory import build_provider

FAKE_RESULTS = [
    {
        "title": "Senior Software Engineer - Backend at Notion",
        "url": "https://boards.greenhouse.io/notion/jobs/12345",
        "snippet": (
            "Notion is hiring a Senior Software Engineer on the Backend team. "
            "Remote in the US. Python, Postgres, distributed systems. Series C+ company."
        ),
        "query": "test",
    },
    {
        "title": "10 best companies to work for in 2026 - TechCrunch",
        "url": "https://techcrunch.com/2026/01/01/best-companies",
        "snippet": (
            "A roundup of the top places to work in tech this year, ranked by "
            "employee satisfaction and compensation."
        ),
        "query": "test",
    },
    {
        "title": "Forward Deployed Engineer - Palantir",
        "url": "https://jobs.lever.co/palantir/abc-def-fde",
        "snippet": (
            "Palantir is hiring Forward Deployed Engineers in NYC and DC. "
            "Work with customers in defense and intelligence sectors."
        ),
        "query": "test",
    },
]

CRITERIA = (
    "Software Engineer or Forward Deployed Engineer roles, USA, remote-friendly. "
    "Avoid defense and intelligence. Avoid blog posts and aggregator pages."
)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    name = sys.argv[1] if len(sys.argv) > 1 else None
    provider = build_provider(name)
    print(f"Provider built. Scoring {len(FAKE_RESULTS)} fake results...\n")
    outcome = provider.score_batch(FAKE_RESULTS, CRITERIA)
    print(f"LLM calls made: {len(outcome.calls)}")
    for c in outcome.calls:
        print(f"  - mode={c.mode} attempt={c.attempt} parsed_ok={c.parsed_ok} "
              f"latency_ms={c.latency_ms} error={c.error!r}")
    print()
    if not outcome.scored:
        print("No results returned. Check provider logs above.")
        return 1
    for sj in outcome.scored:
        src = FAKE_RESULTS[sj.index] if 0 <= sj.index < len(FAKE_RESULTS) else {}
        print(f"[{sj.index}] is_job={sj.is_job} score={sj.score}")
        print(f"    title:   {sj.title}")
        print(f"    company: {sj.company}")
        print(f"    loc:     {sj.location} (remote={sj.remote})")
        print(f"    url:     {src.get('url','')}")
        print(f"    reason:  {sj.reason}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
