# Interview Prep — Job-Search Pipeline

Talking points, narratives, and answers for explaining this project in
technical conversations. Pair with `ARCHITECTURE.md` for diagrams and details.

---

## Elevator pitches

### 30 seconds (the "what")

> I built a Python CLI that automates my own job search. It takes a list of
> Google-style queries, runs them through a self-hosted SearXNG instance or
> the Serper API, then uses an LLM to filter out noise, extract structured
> fields, and score each result against my criteria. Every search result and
> every LLM request/response is stored in Postgres so I can compare providers
> and replay runs. Output is a ranked CSV and a markdown digest.

### 2 minutes (the "why interesting")

> I was tired of scrolling LinkedIn and getting served the same recruiter spam,
> so I built a pipeline that does it for me. The interesting part isn't the
> CLI - it's the abstractions. The LLM backend is pluggable via a single
> config line: OpenAI, Anthropic, Ollama, NVIDIA NIM, or any
> OpenAI-compatible endpoint - no code changes. The search backend has the
> same shape: SearXNG locally, or Serper.dev when the residential IP gets
> CAPTCHA-blocked.
>
> Both layers share a single throttling + retry + persistence pipeline. Every
> LLM request, including failed ones, is preserved in JSONB with provider,
> model, prompts, and raw response. That means I can run the same dataset
> through Claude and through Llama, then SQL-join on the results to see which
> model judges roles differently. It's a small system but it taught me how to
> design real backend-replaceable interfaces, structured-output reliability
> across model classes, and how to handle adversarial rate-limiting from
> upstream APIs.

### 5 minutes (the "walk me through it")

See [Project walkthrough](#project-walkthrough) below.

---

## Project walkthrough

### Trigger / problem

I'm on F-1 OPT with ~3 years of professional experience, looking for mid-level
SWE / Forward Deployed roles. The signal-to-noise ratio on aggregator sites
(LinkedIn, Indeed) was killing me - lots of senior roles, lots of recruiters,
lots of expired posts. I wanted something that filtered for me.

### What it does (one breath)

`titles x sites -> SearXNG/Serper queries -> dedup -> LLM scoring -> ranked
output, with everything persisted to Postgres.`

### How I built it, in the order it happened

1. **Scaffold first.** I started with the simplest possible pipeline: read
   `queries.txt`, hit SearXNG, score with an LLM, write CSV. No DB, no
   abstractions. Got it running end-to-end before adding anything fancy.

2. **Then the LLM provider abstraction.** The core requirement was that
   switching models couldn't require code changes. I noticed that OpenAI,
   Ollama, NVIDIA NIM, Groq, OpenRouter, LM Studio, and vLLM all speak the
   same `/v1/chat/completions` API. So I wrote *one* `OpenAICompatibleProvider`
   parameterized by `(base_url, api_key, model)` and configured each vendor
   as a preset. Anthropic got its own provider because Claude's tool-use isn't
   OpenAI-shaped.

3. **Structured output reliability.** This is where it gets interesting. Big
   hosted models can do function calling. Small Ollama models often can't.
   I built a three-layer fallback: native tool call -> JSON-only prompt ->
   JSON-only with a strict reminder. Every attempt is preserved in the DB.
   A single bad response logs and skips the batch; it cannot crash the run.
   Every parsed response is validated against a Pydantic schema before
   touching Postgres.

4. **Then Postgres for research.** I wanted to compare providers and analyze
   results over time, so I added a 5-table SQLAlchemy schema:
   `runs -> search_queries -> search_results`, with `llm_calls -> scored_results`
   hanging off the run. Every system prompt, user prompt, and raw model
   response is in JSONB. That means I can do things like
   `SELECT provider, count(*) FILTER (WHERE parsed_ok) FROM llm_calls GROUP BY provider`
   and see which models are most reliable on my data.

5. **Then real-world failure modes.** The first time I ran 100 queries in a
   row, Google CAPTCHA'd my IP. SearXNG was returning empty result lists with
   no error. I had to manually open the SearXNG console to discover that
   Google, Brave, DuckDuckGo, and Startpage had all blocked me.
   
   So I added: (a) parsing of SearXNG's `unresponsive_engines` field, (b) a
   per-query log line + per-run summary so failures are visible in the
   terminal, (c) a sliding-window per-minute throttle with jitter so traffic
   doesn't look like a bot, (d) exponential backoff on transient errors, and
   (e) a cool-off period if N consecutive queries return zero results.

6. **Then a second search backend.** Once I understood the failure modes, I
   added Serper.dev as an alternative search backend behind the same
   `Searcher` interface. Same throttling, same persistence, same DB schema.
   Now I can pick `SEARCH_BACKEND = "searxng"` for free local runs or
   `"serper"` when I need reliable Google results.

7. **Documentation last.** ARCHITECTURE.md captures the design decisions;
   README.md is the runbook.

### The thing I'm proudest of

The plugin pattern works at both layers. Two factory files
(`providers/factory.py`, `searchers/factory.py`), two ABCs (`LLMProvider`,
`Searcher`), and the rest of the pipeline never knows which concrete
implementation it's talking to. Adding a third search backend would be one
new file in `searchers/` plus a preset; the pipeline doesn't change.

### What I'd do next

- **Async**, if it mattered (it doesn't - the bottleneck is rate-limiting).
- **Two-provider scoring with disagreement detection** - the schema already
  supports `scored_results.llm_call_id` pointing at different LLM calls per
  row.
- **A FastAPI UI** reading the existing models. No schema changes needed.
- **Embeddings on `snippet`** to dedup by *meaning* rather than just URL.
- **Cron + diff mode** - run hourly, only notify on net-new high-scoring jobs.

---

## Likely interview questions, with answers

### "Walk me through the architecture."

Two pluggable layers (LLM and search), both factory-built behind ABCs. The
pipeline in `main.py` does: build queries (N*M expansion from titles +
sites), persist a `Run` row, hit the search backend for each query via a
throttled `fetch_page`, dedup by normalized URL, batch the deduped results
through `provider.score_batch` which captures every LLM attempt, persist the
parsed scores, then emit CSV + markdown. Postgres stores everything; CSV/MD
is just a snapshot view.

### "Why is the LLM backend pluggable?"

Two reasons. First, **cost flexibility**: I can run free against Ollama
during development, then flip one config line to use Anthropic when I want
quality. Second, **provider comparison**: by storing every prompt and
response in JSONB, I can quantitatively compare models on the same dataset.
That was the hardest constraint to design for - it forced me to capture not
just parsed results but raw payloads, latencies, and failure modes.

### "Why not just use LangChain / LlamaIndex / Pydantic AI?"

I considered it. For this scope - one batched scoring call per provider with
forced structured output - the abstraction surface I'd need from a framework
is tiny. The OpenAI SDK + the Anthropic SDK directly give me ~150 lines of
provider code total, full control over the fallback layers, and zero
dependency churn. A framework would solve the easy 80% and make the hard 20%
(failure handling, custom retry policies, persisting raw payloads) harder.

### "How do you handle the LLM returning bad data?"

Three layers. First, **provider-native structured output** - function
calling for OpenAI-compatible, forced `tool_use` for Anthropic. Second,
**JSON-only fallback prompt** if the model didn't invoke the tool. Third,
**strict reminder** if JSON parsing still fails. Every attempt is logged
to `llm_calls` with `mode`, `parsed_ok`, and the raw payload. Pydantic
validates the parsed output before we ever insert into `scored_results`.
A batch that exhausts all attempts is skipped with a warning - one bad
batch never crashes a 12-batch run.

### "How do you prevent the LLM from hallucinating URLs?"

The model only sees title + url + snippet + an index in the batch. When
parsing the response, I use the model's `index` field to look up the URL
*from the original SearXNG result*. The model can lie about the role title;
it cannot inject a URL. This is enforced at insert time in
`score.py::score_all`.

### "How do you handle being rate-limited?"

Layered. (1) **Jittered minimum spacing** between requests so traffic
doesn't look robotic. (2) **Sliding-window per-minute cap** as a hard
ceiling, enforced globally across the run. (3) **Exponential backoff**
on 429/5xx with retry-max. (4) **Empty-query cool-off** - if 3 consecutive
queries return 0 results, the pipeline pauses for 2 minutes, on the
assumption that upstream engines are CAPTCHA-blocking. (5) **Logging of
per-engine failures from SearXNG's `unresponsive_engines` field** so I see
the issue without opening the search console.

I built this iteratively. The cool-off + engine logging came after I
actually got CAPTCHA'd and had to debug it manually - it's the most useful
piece, and would have saved me ~30 minutes if it'd been there from day one.

### "Why Postgres? Why not SQLite or a flat file?"

Three reasons. **JSONB**: I store raw LLM responses and `unresponsive_engines`
arrays as JSON, and I query into them with `->>` and `jsonb_array_elements`.
SQLite has JSON1 but it's clunkier and not indexed by default. **Future
UI**: I told myself I'd add a UI later, and a SQLAlchemy schema against
Postgres is a 30-minute wire-up to a FastAPI app. **Docker was already in
the stack** for SearXNG. Adding one more container was zero extra friction.

### "Walk me through the schema."

5 tables. `runs` is a row per `python main.py` invocation, capturing the
provider/model/criteria snapshot and run status. `search_queries` is one row
per expanded query - title and site components stored separately so I can
analyze which combinations work. `search_results` is one row per *unique* URL
within a run, enforced by a UNIQUE constraint on `(run_id, normalized_url)`.
`llm_calls` is one row per HTTP call to the LLM provider, including failed
attempts and raw JSON payload - this is the "compare providers" hook.
`scored_results` is the LLM's verdict, with FKs to both the `search_result`
it scored and the `llm_call` that produced the score.

### "How would you add a new LLM provider?"

If the vendor is OpenAI-compatible, just add a preset to `config.PRESETS`
with `base_url`, `key_env`, `model`, and optionally `rpm_limit`. No new
code. If the vendor has its own SDK (like Anthropic does), create a new
class in `providers/` that implements `LLMProvider.score_batch`, then
register it in `providers/factory.py`. That's ~80-120 lines depending on
how good their structured-output support is.

### "What's the biggest weakness?"

The pipeline is synchronous. For 100 queries with rate-limiting it takes
~25 minutes, which is fine for nightly runs but bad for interactive use.
I deliberately didn't go async because the bottleneck is the per-minute
cap, not concurrency - parallelism wouldn't speed it up and would
complicate the throttle layer significantly. The right next step would be
incremental updates (delta-only since last run) rather than concurrency.

### "How did you decide what to persist vs not?"

Heuristic: if I'd need it to answer "why did this run produce these results"
six months from now, persist it. So: full system + user prompts, full raw
JSON response, latencies, errors, the `criteria_text` snapshot, every
attempt not just the successful one. If I'd need it for the next run only,
don't persist - the in-memory `seen` URL set, throttle window state, etc.
The cost of storing ~1 MB of JSONB per run is irrelevant; the value of
being able to A/B providers retroactively is enormous.

---

## STAR-format stories from this project

### Story: Designing the provider abstraction

**Situation:** Spec required swapping between Ollama, OpenAI, NVIDIA,
Anthropic, and any custom endpoint with no code changes.

**Task:** Design an interface that handles all five without duplicating
client code, and without leaking provider-specific concerns into the
pipeline.

**Action:** Noticed that 4 of the 5 (Ollama, OpenAI, NVIDIA, custom) speak
the OpenAI `/v1/chat/completions` shape. Wrote one `OpenAICompatibleProvider`
parameterized by `(base_url, api_key, model, rpm_limit)`. Anthropic got its
own provider because Claude's tool-use isn't OpenAI-shaped. Both implement
the same `score_batch(results, criteria) -> BatchOutcome` interface. A
`factory.build_provider(name)` reads `config.PRESETS[name]` and constructs
the right class. The pipeline calls `provider.score_batch` and never
branches on provider identity.

**Result:** Swapping providers is a single `PROVIDER = "..."` edit. Adding
a new OpenAI-compatible vendor (like Groq or OpenRouter) is a new preset
in a dict, zero new code. Adding a new non-compatible vendor is one new
file. The same pattern was reused for search backends with no design
changes.

### Story: Debugging the CAPTCHA storm

**Situation:** First production-scale run (~100 queries) returned 97
results on attempt 1, then 0 on attempt 2. Nothing logged about why.

**Task:** Find the failure mode and add observability so it wouldn't be
invisible next time.

**Action:** Manually opened the SearXNG web console and discovered every
upstream engine (Google, Brave, DDG, Startpage) was returning "CAPTCHA"
or "too many requests." SearXNG had been silently returning empty result
lists. Dug into the SearXNG JSON response and found the
`unresponsive_engines` field that lists exactly this per-engine state.

Added: per-query logging of the field, run-end aggregated summary with a
CAPTCHA-pattern warning, persistence of the JSON array to a new JSONB
column on `search_queries`. Then added the per-minute throttle + jittered
spacing + empty-query cool-off + exponential backoff layers to prevent
the issue rather than just observe it.

**Result:** The next run that hit a CAPTCHA wall would log
`engines unresponsive: google=CAPTCHA, brave=too many requests` per query
plus a final `WARNING: N CAPTCHA-style failures detected` summary - and
would cool off automatically before triggering deeper blocks. Total time
to diagnose dropped from "manually investigate the search console" to
"read the terminal."

### Story: Three-layer structured output fallback

**Situation:** Pipeline needed to work with both Anthropic (great tool use)
and small Ollama models (often can't function-call at all).

**Task:** Get reliable structured output from both without a model-specific
code path.

**Action:** Built a graceful-degradation chain. Attempt 1: native function
calling with `tool_choice` forcing the schema. Attempt 2 (if no tool was
invoked or arguments didn't parse): plain JSON-mode prompt. Attempt 3 (if
JSON still doesn't parse): same prompt with an explicit "return ONLY a
JSON object with a top-level `jobs` array. No prose, no markdown fences"
reminder. Every attempt is logged to the DB with mode + parsed_ok flags
so I can study failure rates by model.

**Result:** Same code runs against Claude Haiku and against a local
qwen2.5:7b. Failure rates differ - Claude almost always succeeds on
attempt 1, Ollama small models often need attempt 2 - but the pipeline
output is consistent. A batch that exhausts all attempts logs a warning
and is skipped; the run continues.

---

## Skills demonstrated

- **System design:** Two-layer plugin architecture (search + LLM), clean
  separation of concerns (throttling/persistence/dedup don't know which
  backend they're talking to).
- **Backend engineering:** SQLAlchemy 2.x with typed models, Alembic
  migrations, factory + ABC pattern.
- **API integration:** OpenAI SDK, Anthropic SDK, SearXNG JSON API,
  Serper.dev REST API.
- **Reliability engineering:** Layered throttling (jitter + RPM cap +
  backoff + cool-off), schema-validated outputs, graceful degradation
  across attempt modes, full audit trail.
- **DevOps:** Multi-service docker-compose (Postgres, SearXNG, Valkey,
  optional Tor), env-based secret management, idempotent DB bootstrap.
- **LLM application engineering:** Forced structured output across
  providers, JSON schema design, prompt versioning via `criteria_text`
  snapshot, raw-response persistence for replay/comparison.
- **Iterative debugging:** Real failure (CAPTCHA storm) -> observability
  -> prevention. Each layer added in response to evidence, not speculation.

---

## Phrases to use (and avoid)

### Use

- "Pluggable backend" / "factory pattern" - shows you can name what you built.
- "Three-layer fallback" / "graceful degradation" - signals reliability thinking.
- "Schema captures the criteria snapshot" - shows you thought about historical
  comparison.
- "Throttle has jitter + per-minute cap + backoff" - specific, defensible.
- "JSONB so I can query into raw responses" - shows DB literacy.
- "URL from the search result, never from the model" - shows security/integrity
  awareness.

### Avoid

- "It's just a job scraper" - undersells the LLM/abstraction work.
- "I used LangChain to..." - you didn't, and it's a different kind of project
  conversation.
- "It uses ChatGPT" - say "OpenAI" or "Claude" or "Anthropic" specifically.
- "I think it works" - you ran it end-to-end, it works.
