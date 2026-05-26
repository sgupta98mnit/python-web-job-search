# JD fetching + body-based scoring

**Status:** design approved
**Date:** 2026-05-26
**Author:** Sumit Gupta

## Problem

The scoring pipeline today judges each search result from `title`, `url`, `snippet`, and `engine` — the metadata the search backend (SearXNG/Serper) returns. The snippet is typically 1–2 sentences of `<meta description>` or the first matched paragraph. The actual job posting body is never fetched.

This bottoms out scoring precision on borderline jobs (50–75), forces prefilter heuristics and URL host to carry too much weight, and means the LaTeX resume tailoring in [`api/resume.py`](../../../api/resume.py) is working off the same thin snippet, not the JD.

## Goal

Fetch the actual job-posting body for every result that survives prefilter + cache, score from the body, and store the body for downstream use (resume tailoring, future structured-field extraction).

Non-goals (separate specs):

- Structured field extraction (salary, seniority, tech stack) from the body.
- Backfill of older snippet-scored rows.
- Headless-browser fallback for SPA-only pages.
- UI surface for the JD body in `applications/[id]`.

## Scope

- **Which results get fetched:** only items that survive cache + prefilter (~30/run today). Cached and prefiltered items are not fetched.
- **What replaces what:** the body replaces the snippet as the LLM input. There is no two-pass snippet-then-body comparison. (Considered and rejected — doubled LLM cost for analytical value we don't currently need.)
- **Failure behavior:** on any fetch failure, fall back to snippet-scoring and tag the row `source='snippet_fallback'`. Coverage > clean data.

## Pipeline change

```
search_all()                                                  (unchanged)
  -> [SearchResult]
score_all()
  cache hits                                                  (unchanged)
  heuristic prefilter                                         (unchanged)
  NEW: fetcher.fetch_many(remaining) -> {url: FetchOutcome}
  score each item from outcome.body_text OR sr.snippet
  ScoredResult with `source` + `job_description_id`
```

The fetch step lives between prefilter and the LLM call inside [`score.py::score_all`](../../../score.py). `fetcher.fetch_many` is the only thing `score.py` calls — extraction, threadpool, throttling, caching, and persistence are all behind that interface.

## Schema

### New table: `job_descriptions`

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `normalized_url` | text NOT NULL UNIQUE | same normalization as `search_results.normalized_url` |
| `url` | text NOT NULL | original URL fetched |
| `status` | text NOT NULL | `'ok'` \| `'http_error'` \| `'timeout'` \| `'unsupported'` \| `'parse_failed'` |
| `http_status` | int NULL | response code if the server replied |
| `ats` | text NULL | `'greenhouse'` \| `'lever'` \| `'ashby'` \| `'workday'` \| `'generic'` |
| `body_text` | text NULL | extracted JD plain text; null on any failure |
| `body_html_sha256` | char(64) NULL | dedup signal for re-fetches |
| `extractor` | text NOT NULL | which extractor produced `body_text` (e.g. `'greenhouse_v1'`, `'trafilatura'`) |
| `fetched_at` | timestamptz NOT NULL DEFAULT now() | TTL via `fetched_at + 30 days` |
| `error` | text NULL | first ~1000 chars of failure detail |
| `latency_ms` | int NULL | |

Indexes: `(normalized_url)` (UNIQUE), `(fetched_at)` for TTL queries, `(status)` for "show me everything that failed" diagnostics.

Failures are persisted alongside successes so a row exists for every URL we touched. A failure row prevents an immediate re-fetch (cache hit) but expires normally at 30 days so a future run can retry.

Migrations: Alembic autogenerate produces the upgrade; a hand-written companion goes in `db/migrations_sql/2026-05-26_job_descriptions.sql` matching the existing convention.

### Updated table: `scored_results` (additive only)

| column | type | notes |
|---|---|---|
| `source` | text NOT NULL DEFAULT `'body'` | `'body'` \| `'snippet_fallback'` \| `'snippet'` |
| `job_description_id` | int FK `job_descriptions(id)` NULL ON DELETE SET NULL | links to the JD used for scoring; null on snippet/snippet_fallback |

Existing rows backfill to `source='snippet'` (default literal in the migration), so the column is interpretable for historical data without rewriting old runs.

### `llm_calls.mode` unchanged

`mode` is set by the provider and describes *how* the structured-output ladder resolved (`tool_call` / `json_only` / `json_only_retry`) — orthogonal to whether the input was body or snippet. The body-vs-snippet distinction is fully captured by `scored_results.source` and `scored_results.job_description_id`, so `llm_calls.mode` needs no change.

## New package: `fetcher/`

Mirrors the [`searchers/`](../../../searchers/) and [`providers/`](../../../providers/) patterns.

```
fetcher/
  __init__.py
  base.py            # FetchOutcome dataclass; Extractor protocol
  client.py          # fetch_many(session, urls) -> dict[normalized_url, FetchOutcome]
  extractors/
    __init__.py
    generic.py       # trafilatura.extract() wrapper
    greenhouse.py    # selector: div.content / div.app-body / section.content
    lever.py         # selector: div.posting-content
    ashby.py         # selector: div.posting-description; fallback to API endpoint
                     #   https://api.ashbyhq.com/posting-api/job-board/{org}/{id}
    workday.py       # selector: div[data-automation-id='jobPostingDescription']
    registry.py      # url-host -> extractor mapping; falls back to generic
```

### `FetchOutcome`

```python
@dataclass
class FetchOutcome:
    status: Literal["ok", "http_error", "timeout", "unsupported", "parse_failed"]
    ats: str                       # 'greenhouse' | 'lever' | 'ashby' | 'workday' | 'generic'
    body_text: str | None
    http_status: int | None
    error: str | None
    latency_ms: int
    extractor: str                 # e.g. 'greenhouse_v1', 'trafilatura'
    job_description_id: int | None # set after persistence
```

### `fetcher.client.fetch_many` contract

Inputs: a SQLAlchemy session and a list of `(normalized_url, url)` pairs.

Behavior:

1. Query `job_descriptions` for all `normalized_url`s where `fetched_at > now() - JD_CACHE_TTL_DAYS`. Hits short-circuit and return their existing `FetchOutcome` (rebuilt from the row).
2. Misses go into `ThreadPoolExecutor(max_workers=JD_FETCH_WORKERS)`.
3. Each worker:
   - Acquires the per-host token bucket (`JD_FETCH_PER_HOST_RPS`, capacity 1, keyed on host).
   - `requests.get(url, timeout=JD_FETCH_TIMEOUT, headers={"User-Agent": JD_USER_AGENT}, allow_redirects=True)`.
   - Resolves extractor via `registry.for_host(host)`; runs it on the response body.
   - Builds `FetchOutcome`.
4. Persists every outcome (success and failure) via `INSERT ... ON CONFLICT (normalized_url) DO UPDATE`. This guarantees one row per URL and that re-fetches update in place.
5. Returns `{normalized_url: FetchOutcome}` to the caller.

`fetch_many` is the only public surface. Internals (token bucket, threadpool, persistence) are not exported.

### Per-ATS extractors are intentionally dumb

Each is ~20 lines: BeautifulSoup CSS selector → `get_text(separator="\n", strip=True)`. If the selector returns empty, the extractor returns `None` and the registry falls back to `generic.py` (trafilatura) automatically. This gives graceful degradation when an ATS changes its DOM without us noticing — body extraction still works, just via the generic path, and `job_descriptions.extractor` records which one ran.

The Ashby extractor is the one exception: it tries the static page first, and if that fails (Ashby is SPA-heavy), it falls back to Ashby's public posting API (`api.ashbyhq.com/posting-api/job-board/{org}/{id}`), which returns JSON with the JD body. URL parsing extracts `{org}` and `{id}` from `https://jobs.ashbyhq.com/{org}/{id}`.

### Configuration

Added to [`config.py`](../../../config.py):

```python
JD_FETCH_ENABLED: bool = _env_bool("JD_FETCH_ENABLED", True)
JD_FETCH_TIMEOUT: int = _env_int("JD_FETCH_TIMEOUT", 15)
JD_FETCH_WORKERS: int = _env_int("JD_FETCH_WORKERS", 8)
JD_FETCH_PER_HOST_RPS: float = _env_float("JD_FETCH_PER_HOST_RPS", 1.0)
JD_CACHE_TTL_DAYS: int = _env_int("JD_CACHE_TTL_DAYS", 30)
JD_USER_AGENT: str = os.getenv(
    "JD_USER_AGENT",
    "Mozilla/5.0 (compatible; jobsearch/1.0; "
    "+https://github.com/sgupta98mnit/python-web-job-search)",
)
```

Setting `JD_FETCH_ENABLED=false` collapses the fetcher to a no-op; the pipeline behaves exactly as it does today. Important for daemon-mode rollouts, debugging, and benchmarking snippet vs. body precision.

## Failure handling and `source` semantics

For each item entering the LLM step:

| `FetchOutcome.status` | What the scorer sees as "description" | `scored_results.source` | `scored_results.job_description_id` |
|---|---|---|---|
| `ok` | extracted `body_text` | `'body'` | set |
| `http_error` | `sr.snippet` | `'snippet_fallback'` | null |
| `timeout` | `sr.snippet` | `'snippet_fallback'` | null |
| `parse_failed` | `sr.snippet` | `'snippet_fallback'` | null |
| `unsupported` (non-HTML content-type, e.g. PDF, or response too short to be a JD) | `sr.snippet` | `'snippet_fallback'` | null |

The LLM `user_prompt` shape is identical — only the "description" field's source changes. The system prompt gains one line:

> The `description` field is the full job posting body when available, otherwise a short search-result snippet.

No per-mode prompt forking and no provider-layer changes. The existing three-layer structured-output ladder (`tool_call` → `json_only` → `json_only_retry`) continues to set `llm_calls.mode` exactly as today.

## `score.py` change (diff sketch)

```python
# inside score_all, between prefilter and provider.score_batch:
if config.JD_FETCH_ENABLED and to_score:
    outcomes = fetcher.fetch_many(
        session,
        [(sr.normalized_url, sr.url) for sr in to_score],
    )
else:
    outcomes = {}

# _to_dict picks body_text when outcomes[url].status == 'ok',
# else falls back to sr.snippet. Returns (payload_dict, source, jd_id).
prepared = [_to_dict(sr, outcomes.get(sr.normalized_url)) for sr in to_score]
payloads = [p[0] for p in prepared]
# ... existing provider.score_batch call ...
```

After `provider.score_batch` returns, each `ScoredResult` gets `source` + `job_description_id` set from `prepared[index]`.

## Observability

End-of-run print summary, derived purely from in-memory `outcomes` and persisted in `job_descriptions`:

```
JD fetch: 30 urls -> cache=12 ok=14 http_error=2 timeout=1 unsupported=1 parse_failed=0
  ATS mix (ok-only): greenhouse=8 lever=5 ashby=3 generic=10
  Fallbacks to snippet: 4
```

No new aggregate tables; everything is queryable from `job_descriptions` and `scored_results.source`.

## Dependencies

Adds to `requirements.txt`:

- `trafilatura` — generic main-content extraction.
- `beautifulsoup4` + `lxml` — per-ATS selector-based extraction (likely already transitive but pin explicitly).

`requests` is already a dependency. No new system packages.

## Rollout

1. Schema migration (additive, safe to run anytime).
2. Ship `fetcher/` with `JD_FETCH_ENABLED=false` as the default for one daemon cycle; verify migration + cold-start works.
3. Flip `JD_FETCH_ENABLED=true` in a non-prod run; eyeball the end-of-run summary; spot-check a few `scored_results` with `source='body'` to confirm precision improved.
4. Flip in prod via `deploy.env.example` default.

## Open questions resolved during brainstorming

- **Fetch scope:** only LLM-scored items (cache+prefilter survivors), not all 150 results.
- **Score model:** replace snippet-scoring; no parallel two-pass.
- **Extraction:** generic trafilatura + per-ATS overrides for greenhouse/lever/ashby/workday.
- **Failure:** fall back to snippet, tag the row.
- **Placement:** parallel pre-fetch into `job_descriptions`, then sequential scoring from the cached body.
- **Politeness:** per-host 1 req/s throttle, 30-day cache, realistic UA, no robots check (target ATS sites want SEO crawling).
