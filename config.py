"""Central configuration.

Switching LLM backend = changing the single string `PROVIDER` below. No code edits.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Provider selection - THE one knob that swaps the LLM backend.
# Valid values: "ollama", "openai", "nvidia", "anthropic", "custom"
# ---------------------------------------------------------------------------
PROVIDER: str = os.getenv("PROVIDER", "anthropic")


# Per-provider presets. To use a different model on a given provider, edit `model`
# here. To point an OpenAI-compatible provider at a new endpoint, edit `base_url`.
# The `key_env` value names the environment variable to read the API key from.
PRESETS: dict[str, dict[str, str | None]] = {
    "ollama": {
        "kind": "openai_compat",
        "base_url": "http://localhost:11434/v1",
        "key_env": None,          # Ollama ignores the key
        "model": "qwen2.5:7b",
    },
    "openai": {
        "kind": "openai_compat",
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
    },
    "nvidia": {
        "kind": "openai_compat",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "key_env": "NVIDIA_API_KEY",
        "model": os.getenv(
            "NVIDIA_MODEL",
            "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        ),
        "rpm_limit": 40,           # NVIDIA NIM catalog is ~40 req/min
    },
    "anthropic": {
        "kind": "anthropic",
        "base_url": None,          # uses anthropic SDK default
        "key_env": "ANTHROPIC_API_KEY",
        "model": "claude-haiku-4-5",
    },
    "custom": {
        "kind": "openai_compat",
        "base_url": os.getenv("CUSTOM_BASE_URL", "http://localhost:8000/v1"),
        "key_env": "CUSTOM_API_KEY",
        "model": os.getenv("CUSTOM_MODEL", "your-model-here"),
    },
}


# ---------------------------------------------------------------------------
# SearXNG + pipeline tunables
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Search backend - swap with a single string. Same pattern as PROVIDER above.
# Valid values: "searxng" | "serper"
# ---------------------------------------------------------------------------
SEARCH_BACKEND: str = os.getenv("SEARCH_BACKEND", "searxng")

SEARCH_PRESETS: dict[str, dict[str, str | None]] = {
    "searxng": {
        "kind": "searxng",
        "url": os.getenv("SEARXNG_URL", "http://localhost:8888"),
    },
    "serper": {
        "kind": "serper",
        # Serper's /search endpoint is Google. /news, /scholar etc. also exist.
        "url": "https://google.serper.dev/search",
        "key_env": "SERPER_API_KEY",
        "country": "us",   # `gl`
        "language": "en",  # `hl`
        # Results per page (Serper's `num`). Free tier silently returns 0 organic
        # results when num > 10; paid tiers go up to 100. Bump after upgrading.
        "num_per_page": 10,
    },
}

# Kept for backward compatibility / direct override.
SEARXNG_URL: str = os.getenv("SEARXNG_URL", "http://localhost:8888")
# Upper bound on total results per query, summed across all fetched pages.
RESULTS_PER_QUERY: int = 30
# Max SearXNG pages to fetch per query. Stops early if a page returns 0 results
# or once RESULTS_PER_QUERY is reached. Each page is typically ~10 results.
# Going past page 2-3 is the strongest "scraper" signal to Google; keep this low.
PAGES_PER_QUERY: int = 2

# ----- Throttling -----
# Tuned for Google-through-SearXNG from a residential IP: Google CAPTCHAs hard
# above ~1 req/min sustained. These settings keep us under that ceiling, at the
# cost of cycle wall-time. If you switch to a paid backend (Serper) you can
# slash these (e.g. SECONDS_BETWEEN_QUERIES=1, MAX_REQUESTS_PER_MINUTE=60).
SECONDS_BETWEEN_QUERIES: float = 120.0   # 2 min between logical queries
SECONDS_BETWEEN_PAGES: float = 90.0      # 1.5 min between pages of one query
THROTTLE_JITTER: float = 0.4             # 40% +/-

# Sliding-window cap on outbound SearXNG requests, regardless of the delays above.
# 1/min is roughly the sustained ceiling a single residential IP gets from Google.
MAX_REQUESTS_PER_MINUTE: int = 1

# Exponential backoff on transient SearXNG failures (HTTP 429/5xx, timeouts).
RETRY_MAX_ATTEMPTS: int = 4
RETRY_BACKOFF_BASE: float = 5.0          # seconds; doubles each retry
RETRY_BACKOFF_MAX: float = 90.0          # cap per retry

# After this many consecutive zero-result queries, pause the run for the long
# cool-off period instead of plowing on. 0 disables.
COOLOFF_AFTER_EMPTY_QUERIES: int = 2
COOLOFF_SECONDS: float = 1800.0          # 30 min - real recovery time for Google
BATCH_SIZE: int = 8
MIN_SCORE: int = 60
OUTPUT_DIR: str = "output"

# Cost controls for LLM scoring.
# SCORE_CACHE_ENABLED reuses prior scores for the same normalized URL when the
# provider, model, and criteria text match. SCORE_PREFILTER_ENABLED marks
# obvious non-job/search pages without calling the LLM.
SCORE_CACHE_ENABLED: bool = os.getenv("SCORE_CACHE_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
}
SCORE_PREFILTER_ENABLED: bool = os.getenv("SCORE_PREFILTER_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
}

# SearXNG time filter: None | "day" | "week" | "month" | "year"
# "day" ~= last 24 hours (the finest granularity SearXNG exposes).
TIME_RANGE: str | None = "day"

# Appended to every query and used as SearXNG language hint (en-US).
LOCATION: str = "USA"


# ---------------------------------------------------------------------------
# Database (Postgres via docker-compose). Override with DATABASE_URL env var.
# ---------------------------------------------------------------------------
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://jobsearch:jobsearch@localhost:5433/jobsearch",
)


# ---------------------------------------------------------------------------
# CRITERIA - free-text block passed verbatim to the LLM. EDIT THIS to match
# what you actually want.
# ---------------------------------------------------------------------------
CRITERIA: str = """\
CANDIDATE PROFILE
- ~3-4 years of professional software engineering experience.
- Master's in CS (Univ. at Buffalo, Dec 2025). Bachelor's in ECE (NIT Jaipur).
- Strongest stack: Java / Spring Boot, Python, TypeScript, React, PostgreSQL,
  MongoDB, Redis, Kafka, Docker, Kubernetes, AWS, GraphQL.
- Domain depth: SSO / IAM / identity (SAML, OAuth 2.0, OIDC, JWT, PKCE, SCIM)
  from 3 years at miniOrange as the primary developer on their core platform.
  Promoted to Senior Engineer there as the youngest on a 12-person team.
- Heavy enterprise-customer-facing experience: 100+ enterprise customers,
  end-to-end deployments, on-call for prod incidents, REST -> GraphQL migration.
- LLM / agent experience: built agentic workflows with the Gemini API
  (function calling, tool orchestration) and a RAG job-search app on Claude.
- Currently in Buffalo, NY. Open to relocating anywhere in the US.
- F-1 OPT EAD valid until 2027-02-16; STEM OPT extension available.
  No sponsorship cost to the employer, only E-Verify enrollment required.
- Nonresident alien for tax purposes.

TARGET ROLES
- "Software Engineer", "Software Engineer II", "Software Engineer III",
  "Mid-level Software Engineer", "Backend Engineer", "Full Stack Engineer",
  "Platform Engineer", "Forward Deployed Engineer", "Solutions Engineer",
  "Integrations Engineer", "Identity Engineer".
- Mid-level is the sweet spot. Junior / new-grad roles below ~2 yoe are too low.
  Senior or Staff roles asking for 6+ yoe are too high - score those low.
- Forward Deployed / Solutions / Integrations Engineer roles are a strong fit
  given the customer-facing miniOrange background.

PREFER
- Companies that hire F-1 OPT / STEM OPT candidates (most US tech companies do).
- Remote, hybrid (US), or on-site anywhere in the US.
- Backend, full-stack, platform, identity, or developer-tools teams.
- Product-focused startups (Series B+) or established tech companies.

AVOID (score low)
- Senior / Staff / Principal / Lead roles explicitly requiring 6+ years.
- Defense, intelligence, federal contractor, or anything requiring
  US citizenship or an active security clearance (candidate is on F-1 OPT).
- Roles stating "no sponsorship of any kind" or "no OPT / CPT / H-1B".
- Crypto / web3, ad-tech, MLM, unpaid or equity-only listings.
- Recruiter directories, aggregator pages (Indeed, ZipRecruiter, LinkedIn
  search pages), generic blog posts and "best companies" listicles.
- Roles requiring on-site presence outside the US.

When scoring, weight role-level fit heavily: a clear mid-level Software
Engineer role at a reasonable company should be 75-95. A senior role with
6-8+ yoe requirement should be 20-40 even if everything else fits. A clear
new-grad / intern role should be 10-30. Non-job results should be is_job=false.
"""
