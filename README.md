# job-search

End-to-end job-search control plane:

1. A Python pipeline runs Google-style queries through **SearXNG** (free, self-hosted) or **Serper** (paid Google API), uses an LLM to filter noise and score each result against your criteria, and persists every query, result, and LLM call to Postgres.
2. A **FastAPI** service exposes the database as a control-plane API (auth, applications pipeline, tailored resumes, stats, manual search triggers).
3. A **Next.js 15** web UI (cyberpunk theme) gives you a dashboard, jobs feed, and application tracker — applied / interview / offer / rejected with notes.
4. An email digest goes out for new high-scoring jobs, with per-recipient deduplication.

**The LLM backend is pluggable via a single config line** (`PROVIDER`) — Ollama, OpenAI, NVIDIA NIM, Anthropic, or any OpenAI-compatible endpoint. **The search backend is pluggable the same way** (`SEARCH_BACKEND`) — SearXNG or Serper.

## Layout

```
config.py              # PROVIDER + SEARCH_BACKEND + presets + CRITERIA + DATABASE_URL
titles.txt             # one job title per line  (N)
sites.txt              # one site: filter per line (M)
queries.txt            # OPTIONAL override - if non-empty, used verbatim
search.py              # query expansion + dedup + persistence (backend-agnostic)
score.py               # batches results through the LLM, persists every call
notifications.py       # email digests, dedup via email_notifications table
main.py                # CLI / daemon pipeline orchestrator

searchers/
  base.py              # Searcher protocol
  searxng.py           # SearXNG client (throttling, cooloff, retry)
  serper.py            # Serper Google API client (paid)
  factory.py           # build_searcher() from SEARCH_BACKEND

providers/             # LLM provider implementations
  base.py              # LLMProvider interface + ScoredJob + BatchOutcome
  openai_compat.py     # OpenAI / Ollama / NVIDIA / Groq / OpenRouter / vLLM / LM Studio
  anthropic.py         # native Anthropic SDK, forced tool_use
  factory.py

api/                   # FastAPI control plane (served on :8000)
  main.py              # create_app(), CORS, route includes, /healthz
  auth.py              # cookie session auth
  deps.py              # get_session, require_auth
  schemas.py           # pydantic models + STATUSES state machine
  resume.py            # LaTeX resume tailoring (prompt + generation)
  routes/
    auth.py            # login / logout
    applications.py    # list / patch (status transitions, notes)
    resumes.py         # generate + list tailored LaTeX resumes
    stats.py           # /overview, /funnel for dashboard
    search_boost.py    # POST /api/search/serper - manual paid run

web/                   # Next.js 15 + React 19 + Tailwind + Radix UI
  app/(app)/
    dashboard/         # stats overview, score buckets, funnel chart
    jobs/              # job feed with filters
    applications/[id]/ # detail view + status transitions + resume gen
  app/login/
  app/api/[...path]/   # transparent proxy to FastAPI
  components/cyber/    # themed UI (CyberCard, GlitchHeading, ScanlineOverlay, ...)
  components/ui/       # shadcn-style primitives
  middleware.ts        # cookie-gate non-public routes

db/
  models.py            # SQLAlchemy 2.x ORM
  session.py           # engine + session factory
  bootstrap.py         # create_all() on first run
  migrations_sql/      # hand-written SQL migrations (alongside alembic)

migrations/            # Alembic
docker-compose.yml     # local dev: SearXNG + valkey + postgres
docker-compose.prod.yml # prod: + FastAPI + Next.js + Tor
docker-compose.caddy.yml # prod TLS reverse proxy
docs/DEPLOYMENT.md     # full VPS deploy walkthrough
smoke_test.py          # tests the provider layer with fake results
```

## Database

| Table             | One row per                                    |
|-------------------|------------------------------------------------|
| `runs`            | invocation of `python main.py` (status, provider/model snapshot, criteria, totals) |
| `search_queries`  | expanded query within a run (title_part + site_part + raw_result_count + page_counts) |
| `search_results`  | unique URL per run (UNIQUE on normalized URL)  |
| `llm_calls`       | every LLM HTTP call (system + user prompt, raw JSON response, mode, latency, parsed_ok, error) |
| `scored_results`  | LLM verdict on a `search_result` — **plus** application state (`status`, `notes`, `applied_at`, `status_updated_at`) |
| `resume_versions` | one tailored LaTeX resume per `scored_result` generation, linked to the `llm_call` that produced it |
| `email_notifications` | job URL already sent to a recipient by email (UNIQUE on recipient + normalized_url) |

The `scored_results.status` field drives the application pipeline state machine (see `api/routes/applications.py::ALLOWED_TRANSITIONS`):

```
discovered -> saved | applied | rejected | ghosted | irrelevant
saved      -> applied | rejected | ghosted | irrelevant
applied    -> interview | offer | rejected | ghosted | irrelevant
interview  -> offer | rejected | ghosted | irrelevant
offer      -> rejected | irrelevant
rejected   -> applied | irrelevant
ghosted    -> applied | interview | rejected | irrelevant
irrelevant -> discovered | saved
```

## Setup (local dev)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # fill in only the keys you need
```

Bring up SearXNG, Valkey, and Postgres:

```powershell
docker compose up -d
```

This runs `job-search-searxng` (http://localhost:8888), `job-search-valkey`, and `job-search-postgres` (host port **5433** to avoid clashing with a local 5432).

Verify:

```powershell
curl "http://localhost:8888/search?q=hello&format=json"
docker exec -it job-search-postgres psql -U jobsearch -d jobsearch -c "\dt"
```

Tables are empty until the first `python main.py` run, which auto-creates them.

## Picking a provider

Edit one line in [`config.py`](config.py) (or set `PROVIDER` in `.env`):

```python
PROVIDER = "anthropic"  # ollama | openai | nvidia | anthropic | custom
```

| Provider  | Key env            | Default model                                |
|-----------|--------------------|----------------------------------------------|
| ollama    | (none)             | `qwen2.5:7b` (run `ollama pull qwen2.5:7b`)  |
| openai    | `OPENAI_API_KEY`   | `gpt-4o-mini`                                |
| nvidia    | `NVIDIA_API_KEY`   | `nvidia/llama-3.3-nemotron-super-49b-v1.5` (~40 rpm) |
| anthropic | `ANTHROPIC_API_KEY`| `claude-haiku-4-5` (native SDK, tool_use)    |
| custom    | `CUSTOM_API_KEY`   | `CUSTOM_BASE_URL` + `CUSTOM_MODEL` — Groq, OpenRouter, vLLM, LM Studio, etc. |

## Picking a search backend

```python
SEARCH_BACKEND = "searxng"  # or "serper"
```

- **searxng** — free, self-hosted, heavily throttled (Google CAPTCHA-prone on VPS IPs). The pipeline has built-in cooloff (`COOLOFF_AFTER_EMPTY_QUERIES`, `COOLOFF_SECONDS`), per-page sleep, per-query sleep, request/min cap, and exponential backoff. Defaults in `deploy.env.example` are conservative for VPS use.
- **serper** — paid Google API, no CAPTCHA. Set `SERPER_API_KEY`. From the web UI you can trigger a one-off Serper run via the "Boost search" button (POST `/api/search/serper`); the API rejects if another run is in flight.

## Queries

By default the pipeline expands [`titles.txt`](titles.txt) **×** [`sites.txt`](sites.txt) and appends `USA`:

```
"Software Engineer" site:greenhouse.io USA
"Forward Deployed Engineer" site:jobs.lever.co USA
...
```

Drop verbatim lines in [`queries.txt`](queries.txt) to bypass expansion.

## Run

Smoke-test the provider layer (no SearXNG, no DB):

```powershell
python smoke_test.py            # uses config.PROVIDER
python smoke_test.py openai     # override
```

Full pipeline:

```powershell
python main.py                          # one-shot
python main.py --daemon --interval 30   # loop, rotating one title per cycle
python main.py --full-each-run          # daemon, all titles every cycle
python main.py --notify-only            # email-only, no search
python main.py --skip-email             # search/score, no email
python main.py --wait-for-engine google # poll SearXNG until 'google' clears CAPTCHA
```

Daemon mode rotates one title per cycle to spread load across the day. Failed iterations are logged but don't crash the daemon.

Outputs:
- DB rows (see table above)
- `output/jobs_<ts>_run<id>.csv`
- `output/digest_<ts>_run<id>.md`
- one email digest of unsent jobs with score > `EMAIL_SCORE_THRESHOLD`

## Monitoring

Docker production startup supports New Relic APM and application log forwarding
for the API, daemon, and web containers. Set this in `.env` before starting
`docker-compose.prod.yml`:

```env
NEW_RELIC_LICENSE_KEY=your-new-relic-license-key
NEW_RELIC_ENABLED=true
NEW_RELIC_APPLICATION_LOGGING_FORWARDING_ENABLED=true
```

Leave `NEW_RELIC_LICENSE_KEY` blank to run without New Relic.

For full Docker stdout/stderr log forwarding, run the optional infrastructure
agent profile and turn off in-agent log forwarding to avoid duplicates:

```bash
NEW_RELIC_APPLICATION_LOGGING_FORWARDING_ENABLED=false \
docker compose -f docker-compose.prod.yml --env-file .env --profile newrelic-infra up -d --build
```

## Run the API + web UI

```powershell
# terminal 1 - FastAPI on :8000
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000

# terminal 2 - Next.js on :3000
cd web
pnpm install
pnpm dev
```

Open http://localhost:3000, log in, and you'll see:

- **Dashboard** — total scored, status breakdown, score-bucket histogram, 30-day funnel (applied / interview / offer).
- **Jobs** — every scored result, filterable, with one-click status transitions.
- **Applications/[id]** — detail page, notes, status history, tailored-resume generator. The resume route calls the LLM with a LaTeX template + the job's scored info and persists the rendered `.tex` to `resume_versions`.

The Next app proxies `/api/*` to FastAPI via `app/api/[...path]/route.ts`, so the browser only ever hits the Next origin. Auth is a signed cookie (`app_session`) set by the FastAPI `/api/auth/login` route; `middleware.ts` gates every non-public route.

## How it stays cheap and robust

- **Dedup before any LLM call** — normalized URL (lowercase host, strip query+fragment, trim trailing slash), in-memory set per run, UNIQUE constraint at the DB. Cross-run dedup via `--dedup-window-days` (default 30).
- **Score cache** — `SCORE_CACHE_ENABLED` reuses prior scores when the same normalized URL was scored by the same `(provider, model, criteria)`. Massive cost saver across daemon cycles.
- **Score prefilter** — `SCORE_PREFILTER_ENABLED` marks obvious non-job/listicle/search pages without calling the LLM.
- **Batched scoring** controlled by `BATCH_SIZE`.
- **Three-layer structured output** — function-calling → JSON-only prompt → JSON-only with strict reminder. Each attempt is persisted in `llm_calls` with `parsed_ok` so you can study failure modes per model.
- **URLs come from the searcher, never invented by the model.**
- **Crashed runs are kept** with `status='failed'` and `error` populated — evidence beats clean data.
- **SearXNG throttling tuned for Google** — `SECONDS_BETWEEN_QUERIES`, `SECONDS_BETWEEN_PAGES`, `MAX_REQUESTS_PER_MINUTE`, retry+backoff, and a cooloff after N consecutive zero-result queries.

## Schema changes

Alembic is configured; first run uses `create_all()` to bootstrap. To start tracking schema:

```powershell
.\.venv\Scripts\python.exe -m alembic stamp head
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe change"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

For one-off shape changes that don't need Alembic, drop a SQL file in `db/migrations_sql/` (e.g. `2026-05-26_email_notifications.sql`) and apply with `psql`.

## Production deployment

Full walkthrough in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). Summary:

- `docker-compose.prod.yml` brings up Postgres, SearXNG, Valkey, **Tor** (for SearXNG's outbound), the FastAPI container, and the Next.js container.
- `docker-compose.caddy.yml` adds a Caddy reverse proxy with automatic TLS.
- Configure via `deploy.env.example` → `.env` on the VPS (slower throttling profile, real `APP_SECRET`, SMTP creds, optional `SERPER_API_KEY`).

## Cost notes

| Provider  | Per run (~150 results, batch=8, ~19 LLM calls) |
|-----------|------------------------------------------------|
| ollama    | $0 (local)                                     |
| openai    | gpt-4o-mini: ~$0.01-0.05                       |
| nvidia    | varies; many catalog models free under rate cap|
| anthropic | haiku-4-5: ~$0.02-0.10                         |

Serper: ~$0.30 per 1k queries on the cheapest paid tier (free tier is silently capped at `num <= 10`).

## Caveats

- SearXNG only exposes coarse time filters (`day`/`week`/`month`/`year`). `TIME_RANGE="day"` ≈ last 24h. For finer windows, rely on `CRITERIA`.
- `LOCATION="USA"` is appended as a query suffix; the LLM catches non-US leaks.
- Small Ollama models often can't do function calling — the JSON-only fallback handles that. If both fail, try `qwen2.5:14b` or larger.
- Postgres binds host port **5433**, not 5432. Edit `docker-compose.yml` and `DATABASE_URL` to change.
- Serper free tier silently returns 0 organic results when `num > 10` — bump `num_per_page` only after upgrading.
