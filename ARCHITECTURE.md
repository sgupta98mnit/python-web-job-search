# Architecture

A Python CLI that runs Google-style search queries through a pluggable search
backend, uses a pluggable LLM to filter and score the results, and persists
every artifact (queries, results, prompts, raw model responses, scores) to
Postgres for research and a future UI.

## One-paragraph summary

The pipeline takes N job titles x M ATS site patterns, expands them into N*M
queries, runs each through either a self-hosted SearXNG instance or the Serper
Google API, deduplicates results by normalized URL, batches them through an
LLM (Anthropic, OpenAI, NVIDIA NIM, Ollama, or any OpenAI-compatible endpoint)
with forced structured output, validates against a Pydantic schema, and writes
both a ranked CSV/markdown digest and a fully-audited Postgres record of the
run. Every external request is rate-limited; every LLM response is preserved
verbatim so providers/models can be compared side-by-side after the fact.

## Component map

```
+---------------+        +-----------------+         +-----------------+
|  titles.txt   |        |   queries.txt   |         |    sites.txt    |
+-------+-------+        +--------+--------+         +--------+--------+
        |                         |                           |
        +-------------+-----------+---------------------------+
                      |
                      v
              +-------+--------+
              |  build_queries |  (search.py)
              |   - N x M expansion or queries.txt override
              |   - appends LOCATION
              +-------+--------+
                      |
                      v
        +-------------+-------------+
        |        Searcher           |  (searchers/*.py, factory-built)
        |  - SearXNGSearcher        |
        |  - SerperSearcher         |
        +-------------+-------------+
                      |
                      v
        +-------------+-------------+
        |  fetch_page (throttled)   |  (search.py)
        |  - jittered spacing       |
        |  - per-minute cap         |
        |  - retry w/ backoff       |
        +-------------+-------------+
                      |
                      v
        +-------------+-------------+        +--------------------+
        |  search_all               |------->|  Postgres          |
        |  - dedup by norm URL      |        |   runs             |
        |  - persist SearchQuery    |        |   search_queries   |
        |  - persist SearchResult   |        |   search_results   |
        +-------------+-------------+        +--------------------+
                      |
                      v
        +-------------+-------------+
        |  score_all (score.py)     |
        |  - batches of BATCH_SIZE  |
        +-------------+-------------+
                      |
                      v
        +-------------+-------------+
        |       LLMProvider         |  (providers/*.py, factory-built)
        |  - OpenAICompatible       |
        |  - Anthropic              |
        |  3-layer structured       |
        |  output fallback          |
        +-------------+-------------+
                      |
                      v
        +-------------+-------------+        +--------------------+
        |  persist results          |------->|  Postgres          |
        |  - LLMCall (every attempt)|        |   llm_calls        |
        |  - ScoredResult           |        |   scored_results   |
        +-------------+-------------+        +--------------------+
                      |
                      v
              +-------+--------+
              |  CSV + Markdown |
              +----------------+
```

## Tech stack

| Layer       | Choice                          | Why                                                                 |
|-------------|---------------------------------|---------------------------------------------------------------------|
| Language    | Python 3.11+                    | LLM SDK ecosystem, type hints, fast iteration                       |
| Search      | SearXNG (Docker) / Serper API   | Free self-hosted + paid Google fallback                             |
| LLM         | OpenAI SDK / Anthropic SDK      | Cover OpenAI/Ollama/NVIDIA/Groq/etc. via the OpenAI-compatible shape; Anthropic native because Claude tool-use isn't OpenAI-shaped |
| DB          | Postgres 16 (Docker)            | JSONB for raw payloads, strong indexing, future UI/API friendly     |
| ORM         | SQLAlchemy 2.x                  | Idiomatic typed models, works with both Postgres and SQLite later   |
| Migrations  | Alembic                         | Schema evolution without manual ALTERs                              |
| Validation  | Pydantic 2.x                    | Validates every LLM response before persisting                      |
| Cache       | Valkey (Redis fork)             | SearXNG's required result cache                                     |
| Container   | docker-compose                  | One-command bring-up of all services                                |

## Key design decisions

### 1. Provider abstraction over a single OpenAI-compatible client

OpenAI, Ollama, NVIDIA NIM, Groq, OpenRouter, LM Studio, and vLLM all speak the
OpenAI `/v1/chat/completions` shape. Rather than write a client per vendor, we
have **one** `OpenAICompatibleProvider` parameterized by `(base_url, api_key,
model)` and a config preset per vendor. Anthropic gets its own provider because
Claude's native tool-use protocol isn't OpenAI-shaped.

Switching backends is a single `PROVIDER = "..."` line in `config.py`. This was
the core requirement and drives the rest of the abstraction.

Search has the same shape: `SEARCH_BACKEND = "searxng"|"serper"`, factory-built,
shared throttling/persistence/dedup layer above.

### 2. Three-layer structured-output fallback

Small local models (especially via Ollama) often don't support function calling.
Large hosted models do. Same code path must work for both:

1. Try the model's native structured output (`tools` + forced `tool_choice` for
   OpenAI-compatible; `tool_choice={"type":"tool"}` for Anthropic).
2. If the model didn't invoke the tool, retry with a strict "JSON only" prompt.
3. If JSON parsing fails, retry once with an even stricter prompt reminder.

Every attempt is preserved in `llm_calls` with `mode` (`tool_call` /
`json_only` / `json_only_retry`) and `parsed_ok`. A failed batch logs and
continues; one bad response cannot crash the run.

### 3. URL-as-source-of-truth

The LLM never gets to invent URLs. Every `ScoredResult` row's URL comes from
the original `SearchResult` row by `index` into the batch, never from the
model's echo. The model can hallucinate a job title; it cannot hallucinate
a URL into the dataset.

### 4. Persist everything, including failures

The DB stores both `runs.status='failed'` rows and per-call `error` fields. For
LLM calls, the full system prompt, user prompt, and raw JSON response are kept
in JSONB. This is the foundation for two future capabilities the user asked
for:

- **Provider comparison**: replay the same input through a different model and
  diff the scores.
- **Failure analysis**: query why a batch failed (CAPTCHA? schema violation?
  rate limit?) without re-running.

### 5. Dedup before LLM calls

URLs are normalized (lowercase host, strip query string + fragment, trim
trailing slash) and deduplicated at insertion time. A UNIQUE constraint on
`(run_id, normalized_url)` enforces it at the DB level. This matters because
the same job often appears under different greenhouse subdomains
(`boards.greenhouse.io/x/jobs/y` vs `job-boards.greenhouse.io/x/jobs/y`),
and LLM tokens cost money.

### 6. Layered throttling

| Layer | Purpose | Knobs |
|-------|---------|-------|
| Per-request jitter | Mask robot patterns | `THROTTLE_JITTER` |
| Sliding-window RPM cap | Prevent burst-detection | `MAX_REQUESTS_PER_MINUTE` |
| Exponential backoff | Survive transient 429/5xx | `RETRY_MAX_ATTEMPTS`, `RETRY_BACKOFF_BASE` |
| Empty-query cool-off | Detect CAPTCHA cascade and pause | `COOLOFF_AFTER_EMPTY_QUERIES`, `COOLOFF_SECONDS` |
| SearXNG `unresponsive_engines` log | Visibility into per-engine throttling | (always on) |

Built progressively in response to real failures - first CAPTCHA storms across
Google/Brave/DuckDuckGo were detected only by reading the SearXNG console;
adding the engine-failure logging meant the next run surfaced the issue in
the terminal and in the DB.

### 7. NxM query expansion vs verbatim queries.txt

`titles.txt` x `sites.txt` cross-product (N*M queries) is the default. A
non-empty `queries.txt` overrides it for ad-hoc testing. Each persisted
`search_query` row carries `title_part` and `site_part` so you can later
analyze which combinations produced kept jobs.

## Database schema

```
runs (1) ---* search_queries (1) ---* search_results
       \                                       |
        *--- llm_calls (1) ---* scored_results *

runs
  id, started_at, finished_at, status, provider, model, criteria_text,
  time_range, location, results_per_query, batch_size, min_score,
  total_results, total_kept, error

search_queries
  id, run_id, ordinal, query_text, title_part, site_part,
  raw_result_count, error, unresponsive_engines (JSONB), created_at

search_results
  id, run_id, query_id, title, url, normalized_url, snippet, engine,
  page_no, created_at
  UNIQUE (run_id, normalized_url)

llm_calls
  id, run_id, batch_index, provider, model, mode, attempt,
  system_prompt, user_prompt, raw_response (JSONB), parsed_ok,
  latency_ms, error, created_at

scored_results
  id, run_id, search_result_id, llm_call_id,
  is_job, title, company, location, remote, score (0-100), reason,
  kept, created_at
```

JSONB is used deliberately on `raw_response` and `unresponsive_engines` to
allow `->>` and `jsonb_array_elements` queries for ad-hoc analysis without
materializing extra columns.

## Failure modes and what handles them

| Failure                                  | Handling                                    |
|------------------------------------------|---------------------------------------------|
| SearXNG container down                   | requests timeout, run logged as failed      |
| Upstream engines CAPTCHA (Google, Brave) | `unresponsive_engines` logged + persisted; cool-off after N consecutive empties |
| LLM 429 / overload                       | SDK retries internally + provider retries with backoff; batch logged + skipped if exhausted |
| Model returns invalid JSON               | JSON-only retry; if still bad, batch skipped |
| Model returns wrong indexes              | Out-of-range indexes dropped silently       |
| Network hiccup mid-batch                 | exception caught, batch logged, run continues |
| Process killed mid-run                   | DB row stays at `status='running'`; next manual cleanup is `UPDATE runs SET status='failed' WHERE status='running'` |
| Schema column added mid-development      | One-time `ALTER TABLE ADD COLUMN`, then Alembic going forward |

## Extension points

| You want to...                            | Where to add code                              |
|-------------------------------------------|------------------------------------------------|
| Add a new LLM vendor                      | New preset in `config.PRESETS` (if OpenAI-compatible). New class in `providers/` (if not) + register in `factory.py` |
| Add a new search backend                  | New class in `searchers/` implementing `Searcher.fetch_page`, add preset to `config.SEARCH_PRESETS`, register in `searchers/factory.py` |
| Change scoring criteria                   | Edit `config.CRITERIA`. The new value is captured in `runs.criteria_text` so old runs remain comparable. |
| Add a Slack/email notifier               | New module called from `main._run_pipeline` after `score_all`             |
| Add a UI                                 | FastAPI app reading the existing `db/models.py` ORM; no schema change needed |
| Compare two providers on identical input | Two runs back-to-back with `PROVIDER` swapped; join on `search_results.normalized_url` across runs |

## Trade-offs accepted

- **Synchronous, not concurrent.** The full pipeline runs single-threaded.
  For ~100 queries and ~500 results this is ~25 min total, mostly throttled
  sleeps. Going async would not speed up the rate-limited path and would
  complicate the throttle/persistence layers. Punted.
- **No streaming LLM output.** Batched, blocking. Same reasoning as above.
- **No per-result re-scoring/agreement check.** A single model call decides
  each result. A future improvement is to score with two providers and take
  the average / disagreement signal; the schema already supports this
  (`scored_results.llm_call_id` is a FK).
- **Postgres, not SQLite.** SQLite would be simpler but lacks JSONB and
  would need a separate index strategy. Since Docker was already in the
  stack, Postgres added one container and removed two pain points.
- **No retries on the `runs` boundary.** A failed run is logged and you
  re-run manually. Could be a cron + retry-failed CLI later.
