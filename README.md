# job-search

Python CLI that runs Google-style queries through a self-hosted SearXNG instance,
then uses an LLM to filter noise, extract structured fields, and score each result
against your criteria. Every search query, every search result, and every LLM
request/response is persisted to Postgres for research and a future UI. Outputs
a ranked CSV plus a markdown digest.

**The LLM backend is pluggable via a single config line.** Switch between Ollama,
OpenAI, NVIDIA NIM, Anthropic, or any OpenAI-compatible endpoint by editing
[`config.py`](config.py) - no code changes.

## Layout

```
config.py              # PROVIDER + presets + tunables + CRITERIA + DATABASE_URL
titles.txt             # one job title per line  (N)
sites.txt              # one site: filter per line (M)
queries.txt            # OPTIONAL override - if non-empty, used verbatim
search.py              # query expansion + SearXNG client + persistence
score.py               # batches results through the LLM, persists every call
main.py                # end-to-end pipeline, run lifecycle
db/
  models.py            # SQLAlchemy 2.x ORM: Run / SearchQuery / SearchResult
                       #                     LLMCall / ScoredResult
  session.py           # engine + session factory
  bootstrap.py         # create_all() on first run (idempotent)
providers/
  base.py              # LLMProvider interface + ScoredJob + BatchOutcome
  openai_compat.py     # OpenAI / Ollama / NVIDIA / Groq / OpenRouter / vLLM / LM Studio
  anthropic.py         # native Anthropic SDK, forced tool_use
  factory.py           # builds the right provider from config
migrations/            # Alembic - used once you want schema changes tracked
docker-compose.yml     # SearXNG + valkey + postgres
searxng/settings.yml   # JSON format enabled, limiter off
smoke_test.py          # tests the provider layer with fake results, no DB or SearXNG
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill in only the keys for providers you use
```

Start SearXNG **and** Postgres:

```powershell
docker compose up -d
```

This pulls and runs three containers: `job-search-searxng` (http://localhost:8888),
`job-search-valkey` (SearXNG cache), and `job-search-postgres` (port **5433** on the
host to avoid clashing with any local Postgres on 5432).

Verify SearXNG JSON:

```powershell
curl "http://localhost:8888/search?q=hello&format=json"
```

Verify Postgres:

```powershell
docker exec -it job-search-postgres psql -U jobsearch -d jobsearch -c "\dt"
```

(Empty until first `python main.py` run, which auto-creates tables.)

## Picking a provider

Edit one line in [`config.py`](config.py):

```python
PROVIDER = "ollama"  # or "openai" | "nvidia" | "anthropic" | "custom"
```

### Ollama (default, free, local)
```powershell
ollama pull qwen2.5:7b
ollama serve
```
No API key needed.

### OpenAI / NVIDIA / Anthropic
Set the matching key in `.env`:
- OpenAI: `OPENAI_API_KEY` - default model `gpt-4o-mini`
- NVIDIA NIM: `NVIDIA_API_KEY` (prefix `nvapi-`) - rate-limited to ~40 rpm, already wired
- Anthropic: `ANTHROPIC_API_KEY` - default model `claude-haiku-4-5`, uses native SDK

### Custom
`PROVIDER = "custom"`, then either edit `PRESETS["custom"]` or set
`CUSTOM_BASE_URL`, `CUSTOM_API_KEY`, `CUSTOM_MODEL` in `.env`. Works with Groq,
OpenRouter, Together, Fireworks, vLLM, LM Studio, etc.

## Queries: titles x sites

By default the pipeline expands [`titles.txt`](titles.txt) **x** [`sites.txt`](sites.txt)
into N x M queries and appends `USA` to each. Example:

```
"Software Engineer" site:greenhouse.io USA
"Software Engineer" site:jobs.lever.co USA
"Software Engineer" site:ashbyhq.com USA
"Forward Deployed Engineer" site:greenhouse.io USA
...
```

To bypass expansion temporarily, drop verbatim queries into
[`queries.txt`](queries.txt) - any non-comment line there overrides the expansion.

## Run

Smoke-test the provider layer (no SearXNG, no DB):

```powershell
python smoke_test.py            # uses config.PROVIDER
python smoke_test.py openai     # override on the command line
```

Full pipeline (writes to DB + filesystem):

```powershell
python main.py
```

Outputs:
- DB rows under `runs`, `search_queries`, `search_results`, `llm_calls`, `scored_results`
- `output/jobs_<ts>_run<id>.csv`
- `output/digest_<ts>_run<id>.md`

## What gets stored where

| Table             | One row per                                    |
|-------------------|------------------------------------------------|
| `runs`            | invocation of `python main.py` (status, provider/model snapshot, criteria, totals) |
| `search_queries`  | expanded query within a run (title_part + site_part + raw_result_count) |
| `search_results`  | unique URL (UNIQUE per run on normalized URL)  |
| `llm_calls`       | every LLM HTTP call we made (system + user prompt, raw JSON response, mode, latency, parsed_ok, error) |
| `scored_results`  | LLM verdict on a `search_result` (kept = passed `MIN_SCORE`) |

This is enough to:
- compare two providers on the same input (filter `llm_calls` by `provider`)
- inspect why a result was rejected (`scored_results.reason`, `llm_calls.raw_response`)
- replay a run later
- back a future UI (Run -> Queries -> Results -> Scores)

Useful queries to start with:

```sql
-- provider quality side-by-side
SELECT provider, model, count(*) FILTER (WHERE parsed_ok) AS ok,
       count(*) AS total, avg(latency_ms)::int AS avg_ms
FROM llm_calls GROUP BY provider, model;

-- top-scoring kept jobs across all runs
SELECT s.score, s.title, s.company, sr.url
FROM scored_results s JOIN search_results sr ON sr.id = s.search_result_id
WHERE s.kept ORDER BY s.score DESC LIMIT 50;

-- which queries are wasting calls (returning 0 useful results)
SELECT q.query_text, q.raw_result_count
FROM search_queries q LEFT JOIN scored_results s ON s.run_id = q.run_id
GROUP BY q.id HAVING count(s.id) FILTER (WHERE s.kept) = 0
ORDER BY q.raw_result_count DESC;
```

## Schema changes later

The repo ships with Alembic configured but no migrations yet (first run uses
`create_all()` to bootstrap). When you want to start tracking changes:

```powershell
# baseline (one-time, after Postgres is up and tables exist)
.\.venv\Scripts\python.exe -m alembic stamp head

# then for every schema change
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe change"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## How it stays cheap and robust

- Dedup before any LLM call: normalized URL (lowercase host, strip query +
  fragment, trim trailing slash) plus an in-memory set per run, backed by a
  UNIQUE constraint at the DB level.
- Batched scoring controlled by `BATCH_SIZE`.
- Structured output, three layers deep: function-calling -> JSON-only prompt
  -> JSON-only with strict reminder. Each attempt is persisted in `llm_calls`
  with `parsed_ok` so you can study failure modes per model.
- URLs are always taken from the SearXNG result, never invented by the model.
- A run that crashes partway is **kept** in the DB with `status='failed'` and the
  `error` column populated - evidence beats clean data here.

## Caveats

- SearXNG only exposes coarse time filters (`day`/`week`/`month`/`year`). `TIME_RANGE`
  defaults to `"day"` (~ last 24h). For finer windows, rely on the LLM `CRITERIA`.
- `LOCATION = "USA"` is appended as a query suffix and SearXNG is asked for `en-US`.
  Non-US results can still leak through; the LLM scoring catches them.
- Small local Ollama models sometimes can't do function calling. The JSON-only
  fallback handles that; if both fail, try `qwen2.5:14b` or larger.
- Postgres binds to host port **5433**, not 5432. Edit `docker-compose.yml` if
  you need otherwise (and update `DATABASE_URL` in `config.py` to match).

## Cost notes

| Provider  | Per run (~150 results, batch=8, ~19 LLM calls) |
|-----------|------------------------------------------------|
| ollama    | $0 (local)                                     |
| openai    | gpt-4o-mini: ~$0.01-0.05                       |
| nvidia    | varies by model; many free-tier under rate cap |
| anthropic | haiku-4-5: ~$0.02-0.10                         |
