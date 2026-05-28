"""Central configuration.

Switching LLM backend = changing the single string `PROVIDER` below. No code edits.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.lower() in {"1", "true", "yes", "on"}


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
        # NVIDIA is free; bias toward accuracy by scoring one job per call.
        "batch_size": 1,
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
RESULTS_PER_QUERY: int = _env_int("RESULTS_PER_QUERY", 30)
# Max SearXNG pages to fetch per query. Stops early if a page returns 0 results
# or once RESULTS_PER_QUERY is reached. Each page is typically ~10 results.
# Going past page 2-3 is the strongest "scraper" signal to Google; keep this low.
PAGES_PER_QUERY: int = _env_int("PAGES_PER_QUERY", 2)

# ----- Throttling -----
# Tuned for Google-through-SearXNG. VPS/data-center IPs tend to hit CAPTCHA and
# block thresholds sooner than residential IPs, so deploy.env.example sets a
# slower profile. If you switch to a paid backend (Serper), you can slash these
# e.g. SECONDS_BETWEEN_QUERIES=1, MAX_REQUESTS_PER_MINUTE=60.
SECONDS_BETWEEN_QUERIES: float = _env_float("SECONDS_BETWEEN_QUERIES", 120.0)
SECONDS_BETWEEN_PAGES: float = _env_float("SECONDS_BETWEEN_PAGES", 90.0)
THROTTLE_JITTER: float = _env_float("THROTTLE_JITTER", 0.4)

# Sliding-window cap on outbound SearXNG requests, regardless of the delays above.
# 1/min is a conservative ceiling; use the delay settings above for wider spacing.
MAX_REQUESTS_PER_MINUTE: int = _env_int("MAX_REQUESTS_PER_MINUTE", 1)

# Exponential backoff on transient SearXNG failures (HTTP 429/5xx, timeouts).
RETRY_MAX_ATTEMPTS: int = _env_int("RETRY_MAX_ATTEMPTS", 4)
RETRY_BACKOFF_BASE: float = _env_float("RETRY_BACKOFF_BASE", 5.0)
RETRY_BACKOFF_MAX: float = _env_float("RETRY_BACKOFF_MAX", 90.0)

# After this many consecutive zero-result queries, pause the run for the long
# cool-off period instead of plowing on. 0 disables.
COOLOFF_AFTER_EMPTY_QUERIES: int = _env_int("COOLOFF_AFTER_EMPTY_QUERIES", 2)
COOLOFF_SECONDS: float = _env_float("COOLOFF_SECONDS", 1800.0)
BATCH_SIZE: int = _env_int("BATCH_SIZE", 8)
MIN_SCORE: int = _env_int("MIN_SCORE", 60)
OUTPUT_DIR: str = "output"

# Deterministic post-LLM safety net. When the LLM mistakenly scores a non-US
# role highly (despite the LOCATION HARD GATE in CRITERIA) or returns a borderline
# score, we still mark the row as auto-rejected so it doesn't pollute the review
# queue. Tags persisted to scored_results.rejection_reason.
AUTO_REJECT_ENABLED: bool = _env_bool("AUTO_REJECT_ENABLED", True)
AUTO_REJECT_MIN_SCORE: int = _env_int("AUTO_REJECT_MIN_SCORE", 35)
AUTO_REJECT_REQUIRE_USA: bool = _env_bool("AUTO_REJECT_REQUIRE_USA", True)

# Email notifications. The pipeline sends one digest of previously unsent jobs
# whose score is strictly above EMAIL_SCORE_THRESHOLD.
EMAIL_NOTIFICATIONS_ENABLED: bool = _env_bool("EMAIL_NOTIFICATIONS_ENABLED", True)
EMAIL_TO: str = os.getenv("EMAIL_TO", "sgupta98mnit@gmail.com")
EMAIL_SCORE_THRESHOLD: int = _env_int("EMAIL_SCORE_THRESHOLD", 50)
# Email is sent via Resend (https://resend.com). The free tier only allows
# sending FROM `onboarding@resend.dev` TO the address that owns the API key.
# To send from your own address, verify a domain at https://resend.com/domains
# and set EMAIL_FROM=alerts@yourdomain.com.
EMAIL_FROM: str = os.getenv("EMAIL_FROM", "onboarding@resend.dev")
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
RESEND_API_URL: str = os.getenv("RESEND_API_URL", "https://api.resend.com/emails")
RESEND_TIMEOUT: int = _env_int("RESEND_TIMEOUT", 15)

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

# ---------------------------------------------------------------------------
# Job-description fetcher (see docs/superpowers/specs/2026-05-26-jd-fetching-design.md)
# Disabled => pipeline scores from snippets exactly as before.
# ---------------------------------------------------------------------------
JD_FETCH_ENABLED: bool = _env_bool("JD_FETCH_ENABLED", True)
JD_FETCH_TIMEOUT: int = _env_int("JD_FETCH_TIMEOUT", 15)
JD_FETCH_WORKERS: int = _env_int("JD_FETCH_WORKERS", 8)
JD_FETCH_PER_HOST_RPS: float = _env_float("JD_FETCH_PER_HOST_RPS", 1.0)
JD_CACHE_TTL_DAYS: int = _env_int("JD_CACHE_TTL_DAYS", 30)
JD_MIN_BODY_CHARS: int = _env_int("JD_MIN_BODY_CHARS", 400)
JD_USER_AGENT: str = os.getenv(
    "JD_USER_AGENT",
    "Mozilla/5.0 (compatible; jobsearch/1.0; "
    "+https://github.com/sgupta98mnit/python-web-job-search)",
)

# Jina Reader fallback. When the native fetch yields parse_failed / unsupported
# / http_error / timeout, retry once through https://r.jina.ai/<url>. Free
# service, no API key required, renders JS-heavy pages server-side and returns
# clean markdown.
JD_JINA_ENABLED: bool = _env_bool("JD_JINA_ENABLED", True)
JD_JINA_TIMEOUT: int = _env_int("JD_JINA_TIMEOUT", 30)
JD_JINA_BASE_URL: str = os.getenv("JD_JINA_BASE_URL", "https://r.jina.ai/")

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
LOCATION (HARD GATE - APPLY FIRST)
- The candidate is on F-1 OPT and will ONLY take US-based roles.
- If the posting's location is outside the United States (India, Canada,
  EU, UK, LATAM, APAC, MENA, etc.) the score MUST be 15 or lower regardless
  of how well the role otherwise fits. This is a hard rule, not a preference.
- US-remote, US-hybrid, and US-on-site all qualify as US-based.
- If location is ambiguous or unstated, infer from the company HQ, the job
  board (e.g. naukri.com, indeed.in implies India) and the title/snippet
  language. When still unclear, lean toward "not US" and score low.
- Roles requiring on-site presence outside the US: score <= 15.

CANDIDATE PROFILE
- ~3-4 years of professional software engineering experience.
- Master's in CS (Univ. at Buffalo, Dec 2025). Bachelor's in ECE (NIT Jaipur).
- Strongest stack: Java / Spring Boot, Python, TypeScript, React, PostgreSQL,
  MongoDB, Redis, Kafka, Docker, Kubernetes, AWS, GraphQL, Shopify.
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

ROLE FIT - SKILLS, NOT TITLES
- Any role title is acceptable: Software Engineer, Backend, Full-Stack,
  Platform, Solutions, Forward Deployed, Integrations, Identity, Implementation,
  Technical Support Engineer, Customer Engineer, Sales Engineer, Developer
  Support, Data / Analytics Engineer, Shopify Developer, Python / Java
  Developer, etc. Do not penalize a posting just because the title is not
  "Software Engineer".
- What matters is whether the day-to-day work uses the candidate's skills.
  Score high when the JD involves any of:
    * SSO / IAM / identity protocols (SAML, OAuth, OIDC, SCIM, JWT, PKCE)
    * Java / Spring Boot
    * Python
    * TypeScript / React / Node
    * PostgreSQL / MongoDB / Redis
    * Kafka, RabbitMQ, message queues
    * Docker / Kubernetes / AWS
    * GraphQL / REST API design
    * Shopify (apps, themes, Shopify Plus integrations)
    * LLM / agent / RAG work
- Identity / SSO matches are the strongest fit given the miniOrange background.
- A "Technical Support Engineer" or "Solutions Engineer" role that involves
  troubleshooting SAML / OAuth / API integrations is a strong fit. A generic
  customer-service or tier-1 helpdesk role with no technical skill overlap
  is not.

SENIORITY
- Mid-level (~2-5 yoe) is the sweet spot.
- Junior / new-grad / intern roles below ~2 yoe: score 10-30.
- Senior / Staff / Principal / Lead roles requiring 6+ yoe: score 20-40
  even if everything else fits.

AVOID (score low regardless of other fit)
- Defense, intelligence, federal contractor, or anything requiring
  US citizenship or an active security clearance.
- Roles stating "no sponsorship of any kind" or "no OPT / CPT / H-1B".
- Crypto / web3, ad-tech, MLM, unpaid or equity-only listings.
- Recruiter directories, aggregator pages (Indeed, ZipRecruiter, LinkedIn
  search pages), generic blog posts and "best companies" listicles
  (these should be is_job=false).

SCORING GUIDE (after applying the LOCATION gate)
- Clear mid-level role with strong skill overlap at a reasonable US company: 75-95.
- Mid-level role with partial skill overlap: 55-75.
- Mid-level role with only weak/tangential skill overlap: 30-55.
- Senior role requiring 6+ yoe: 20-40.
- New-grad / intern role: 10-30.
- Non-job results: is_job=false.
"""
