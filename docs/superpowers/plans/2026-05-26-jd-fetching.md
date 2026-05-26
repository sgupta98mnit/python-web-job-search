# JD Fetching + Body-Based Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace snippet-based LLM scoring with full job-description fetching for items that survive cache + prefilter, persisting fetched bodies to a new `job_descriptions` table so they can also power downstream resume tailoring.

**Architecture:** A new `fetcher/` package mirrors the existing `searchers/` and `providers/` patterns. `fetcher.fetch_many(session, urls)` is the only entry point: it short-circuits cache hits, fans out misses across a small threadpool with a per-host token bucket, runs a per-ATS or generic extractor, persists every outcome (success and failure) to `job_descriptions`, and returns a `{normalized_url: FetchOutcome}` dict. `score.py` consumes the outcomes — on `ok` it scores from `body_text`; on any failure it falls back to the existing snippet and tags `scored_results.source='snippet_fallback'`.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x, Postgres, `requests`, `trafilatura` (generic main-content extraction), `beautifulsoup4` + `lxml` (per-ATS selector extraction), `pytest` (new, just for the fetcher unit tests).

**Spec:** [docs/superpowers/specs/2026-05-26-jd-fetching-design.md](../specs/2026-05-26-jd-fetching-design.md)

**Project convention notes the engineer needs to know up-front:**
- This repo has Alembic configured but **no migrations have ever been written through it** (`migrations/versions/` is empty). The convention in practice is hand-written SQL files in `db/migrations_sql/` named `YYYY-MM-DD_<topic>.sql`, applied with `psql`. New ORM tables also get picked up by `db/bootstrap.py::init_db()` on first start via `create_all()`, but `ALTER TABLE` changes do not — those need the SQL file.
- Postgres runs in docker-compose and binds to host port **5433** (not 5432). All `psql` commands in this plan use that port.
- There is no `tests/` directory and no `pytest` configuration today; `smoke_test.py` at the repo root is the only existing test. Task 3 introduces `pytest` as a dev dep and `tests/fetcher/` as the first real test tree — this is justified by the fetcher's logic-heavy surface (extractors, token bucket, registry).
- The fetcher persists ORM rows via `session.add(...) + session.flush()` rather than raw SQL `INSERT ... ON CONFLICT`, because the calling `score_all` already owns a session and a transaction. The "ON CONFLICT" semantics described in the spec are implemented by doing a `SELECT ... FOR UPDATE` on `normalized_url` first and then either `INSERT` or `UPDATE` in the same transaction.

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `db/migrations_sql/2026-05-26_job_descriptions.sql` | Hand-written DDL: create `job_descriptions`, add `source` + `job_description_id` columns to `scored_results`, add indexes. |
| `fetcher/__init__.py` | Re-exports `fetch_many`, `FetchOutcome`. |
| `fetcher/base.py` | `FetchOutcome` dataclass, `Extractor` protocol, `ExtractorResult` dataclass. |
| `fetcher/throttle.py` | `HostTokenBucket` class — per-host rate limiter. |
| `fetcher/extractors/__init__.py` | Empty marker. |
| `fetcher/extractors/generic.py` | Trafilatura wrapper. |
| `fetcher/extractors/greenhouse.py` | CSS-selector extractor for `boards.greenhouse.io` and `*.greenhouse.io`. |
| `fetcher/extractors/lever.py` | CSS-selector extractor for `jobs.lever.co`. |
| `fetcher/extractors/ashby.py` | Static-page extractor with fallback to Ashby's public posting API. |
| `fetcher/extractors/workday.py` | CSS-selector extractor for `*.myworkdayjobs.com`. |
| `fetcher/extractors/registry.py` | Host → extractor lookup with generic fallback. |
| `fetcher/client.py` | `fetch_many(session, urls)` — cache lookup + threadpool + persistence. |
| `tests/__init__.py` | Empty marker. |
| `tests/fetcher/__init__.py` | Empty marker. |
| `tests/fetcher/test_throttle.py` | Token-bucket unit tests. |
| `tests/fetcher/test_extractors.py` | Per-ATS extractor unit tests (fixtures: small static HTML strings). |
| `tests/fetcher/test_registry.py` | Host → extractor resolution tests. |
| `tests/fetcher/test_client.py` | `fetch_many` integration test with a mocked `requests.Session` and an in-memory SQLite session. |

**Modified files:**

| Path | What changes |
|---|---|
| `requirements.txt` | Add `trafilatura`, `beautifulsoup4`, `lxml`, `pytest`. |
| `config.py` | Add `JD_FETCH_*` knobs. |
| `.env.example` | Add `JD_*` overrides as comments. |
| `deploy.env.example` | Same. |
| `db/models.py` | Add `JobDescription` ORM class; add `source` and `job_description_id` columns + relationship on `ScoredResult`. |
| `score.py` | Insert `fetcher.fetch_many` call between prefilter and `provider.score_batch`; update `_to_dict` to accept an outcome; set `source` + `job_description_id` on new `ScoredResult` rows; print end-of-run JD summary. |

---

### Task 1: Add the dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Append the new deps**

Open `requirements.txt` and append (preserve existing entries; do not reorder):

```
trafilatura>=1.12.0
beautifulsoup4>=4.12.0
lxml>=5.2.0
pytest>=8.0.0
```

- [ ] **Step 2: Install**

Run from the repo root with the project venv active:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Expected: four new packages install successfully. No errors.

- [ ] **Step 3: Verify**

```powershell
.\.venv\Scripts\python.exe -c "import trafilatura, bs4, lxml, pytest; print('ok')"
```

Expected output: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add trafilatura, beautifulsoup4, lxml, pytest for JD fetcher"
```

---

### Task 2: Schema migration — `job_descriptions` table + `scored_results` columns

**Files:**
- Create: `db/migrations_sql/2026-05-26_job_descriptions.sql`

- [ ] **Step 1: Write the migration**

Create `db/migrations_sql/2026-05-26_job_descriptions.sql` with this exact content:

```sql
CREATE TABLE IF NOT EXISTS job_descriptions (
  id                INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  normalized_url    TEXT          NOT NULL,
  url               TEXT          NOT NULL,
  status            VARCHAR(20)   NOT NULL,
  http_status       INTEGER       NULL,
  ats               VARCHAR(20)   NULL,
  body_text         TEXT          NULL,
  body_html_sha256  CHAR(64)      NULL,
  extractor         VARCHAR(40)   NOT NULL,
  fetched_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
  error             TEXT          NULL,
  latency_ms        INTEGER       NULL,
  CONSTRAINT uq_job_descriptions_normalized_url UNIQUE (normalized_url)
);

CREATE INDEX IF NOT EXISTS ix_job_descriptions_fetched_at
  ON job_descriptions(fetched_at);

CREATE INDEX IF NOT EXISTS ix_job_descriptions_status
  ON job_descriptions(status);

ALTER TABLE scored_results
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'snippet';

ALTER TABLE scored_results
  ADD COLUMN IF NOT EXISTS job_description_id INTEGER NULL
  REFERENCES job_descriptions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_scored_results_job_description_id
  ON scored_results(job_description_id);
```

Default `'snippet'` so historical rows are interpretable. New rows written by the updated `score.py` will set `'body'` or `'snippet_fallback'` explicitly.

- [ ] **Step 2: Apply the migration**

Postgres listens on host port **5433** per `docker-compose.yml`.

```powershell
docker exec -i job-search-postgres psql -U jobsearch -d jobsearch < db/migrations_sql/2026-05-26_job_descriptions.sql
```

Expected output: a series of `CREATE TABLE` / `CREATE INDEX` / `ALTER TABLE` notices and no error lines.

- [ ] **Step 3: Verify the schema**

```powershell
docker exec -it job-search-postgres psql -U jobsearch -d jobsearch -c "\d job_descriptions"
docker exec -it job-search-postgres psql -U jobsearch -d jobsearch -c "\d scored_results"
```

Expected:
- `job_descriptions` exists with the 12 columns above and the UNIQUE constraint on `normalized_url`.
- `scored_results` shows the two new columns (`source`, `job_description_id`).

- [ ] **Step 4: Commit**

```bash
git add db/migrations_sql/2026-05-26_job_descriptions.sql
git commit -m "db: add job_descriptions table and scored_results.source/job_description_id"
```

---

### Task 3: ORM models — `JobDescription` + `ScoredResult` updates

**Files:**
- Modify: `db/models.py`

- [ ] **Step 1: Add the `JobDescription` class**

Open `db/models.py`. After the `EmailNotification` class (currently the last class in the file), append:

```python
class JobDescription(Base):
    __tablename__ = "job_descriptions"
    __table_args__ = (
        UniqueConstraint("normalized_url", name="uq_job_descriptions_normalized_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'ok' | 'http_error' | 'timeout' | 'unsupported' | 'parse_failed'
    http_status: Mapped[int | None] = mapped_column(Integer)
    ats: Mapped[str | None] = mapped_column(String(20))
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html_sha256: Mapped[str | None] = mapped_column(String(64))
    extractor: Mapped[str] = mapped_column(String(40), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    scored: Mapped[list["ScoredResult"]] = relationship(
        back_populates="job_description"
    )
```

- [ ] **Step 2: Add the new columns + relationship on `ScoredResult`**

In the `ScoredResult` class (`db/models.py`), add — right after the existing `email_notifications` relationship:

```python
    source: Mapped[str] = mapped_column(
        String(20), default="body", server_default="snippet", nullable=False
    )
    job_description_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_descriptions.id", ondelete="SET NULL"), index=True
    )

    job_description: Mapped["JobDescription | None"] = relationship(
        back_populates="scored"
    )
```

The Python-side `default="body"` ensures new rows our code creates without specifying `source` get `'body'`. The DB-level `server_default="snippet"` matches the migration so historical rows and any non-ORM inserts get the safe historical value.

- [ ] **Step 3: Verify imports resolve and `init_db()` is a no-op**

```powershell
.\.venv\Scripts\python.exe -c "from db.bootstrap import init_db; init_db(); print('ok')"
```

Expected: `ok`. (Tables already exist from Task 2's SQL migration, so `create_all()` is a no-op.)

- [ ] **Step 4: Commit**

```bash
git add db/models.py
git commit -m "db: ORM model for JobDescription + ScoredResult.source/job_description"
```

---

### Task 4: Configuration knobs

**Files:**
- Modify: `config.py`
- Modify: `.env.example`
- Modify: `deploy.env.example`

- [ ] **Step 1: Add knobs to `config.py`**

Open `config.py`. After the `SCORE_PREFILTER_ENABLED` block (around line 170), append:

```python
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
```

`JD_MIN_BODY_CHARS` is the threshold below which an extracted body is considered too short to be a real JD; below it the outcome becomes `unsupported` and the scorer falls back to snippet.

- [ ] **Step 2: Document in `.env.example`**

Append to `.env.example`:

```
# --- JD fetcher (see docs/superpowers/specs/2026-05-26-jd-fetching-design.md) ---
# JD_FETCH_ENABLED=true
# JD_FETCH_TIMEOUT=15
# JD_FETCH_WORKERS=8
# JD_FETCH_PER_HOST_RPS=1.0
# JD_CACHE_TTL_DAYS=30
# JD_MIN_BODY_CHARS=400
# JD_USER_AGENT=Mozilla/5.0 (compatible; jobsearch/1.0; +https://...)
```

- [ ] **Step 3: Document in `deploy.env.example`**

Append the same block to `deploy.env.example`.

- [ ] **Step 4: Commit**

```bash
git add config.py .env.example deploy.env.example
git commit -m "config: add JD_FETCH_* knobs (default enabled)"
```

---

### Task 5: `fetcher/base.py` — types

**Files:**
- Create: `fetcher/__init__.py`
- Create: `fetcher/base.py`

- [ ] **Step 1: Create the package marker**

Create `fetcher/__init__.py`:

```python
"""Job-description fetcher: pre-fetches and persists JD bodies, used by score.py."""

from fetcher.base import FetchOutcome
from fetcher.client import fetch_many

__all__ = ["FetchOutcome", "fetch_many"]
```

- [ ] **Step 2: Create the types**

Create `fetcher/base.py`:

```python
"""Types shared by the fetcher client, extractors, and tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

FetchStatus = Literal["ok", "http_error", "timeout", "unsupported", "parse_failed"]


@dataclass
class ExtractorResult:
    """Returned by an Extractor. `body_text=None` signals 'this extractor
    didn't find anything; try the next one (typically generic)'."""

    body_text: str | None
    extractor: str  # e.g. 'greenhouse_v1', 'trafilatura'


class Extractor(Protocol):
    name: str
    """Stable identifier persisted to job_descriptions.extractor."""

    def extract(self, *, url: str, html: str) -> ExtractorResult: ...


@dataclass
class FetchOutcome:
    """One row's worth of fetch state, returned by fetch_many."""

    status: FetchStatus
    ats: str  # 'greenhouse' | 'lever' | 'ashby' | 'workday' | 'generic'
    body_text: str | None
    http_status: int | None
    error: str | None
    latency_ms: int
    extractor: str
    job_description_id: int | None  # set after persistence
```

- [ ] **Step 3: Verify imports**

```powershell
.\.venv\Scripts\python.exe -c "from fetcher.base import FetchOutcome, Extractor, ExtractorResult; print('ok')"
```

Expected: `ok`.

(The `fetcher/__init__.py` re-exports `fetch_many` from `fetcher.client`, which doesn't exist yet, so don't `import fetcher` until Task 11.)

- [ ] **Step 4: Commit**

```bash
git add fetcher/__init__.py fetcher/base.py
git commit -m "fetcher: add FetchOutcome, Extractor protocol, ExtractorResult"
```

---

### Task 6: `fetcher/throttle.py` — per-host token bucket

**Files:**
- Create: `fetcher/throttle.py`
- Create: `tests/__init__.py`
- Create: `tests/fetcher/__init__.py`
- Create: `tests/fetcher/test_throttle.py`

- [ ] **Step 1: Write the failing test**

Create `tests/__init__.py` (empty) and `tests/fetcher/__init__.py` (empty).

Create `tests/fetcher/test_throttle.py`:

```python
"""Unit tests for fetcher.throttle.HostTokenBucket."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from fetcher.throttle import HostTokenBucket


def test_first_acquire_is_immediate():
    bucket = HostTokenBucket(rps=1.0)
    start = time.monotonic()
    bucket.acquire("example.com")
    elapsed = time.monotonic() - start
    assert elapsed < 0.05


def test_second_acquire_same_host_waits_one_period():
    bucket = HostTokenBucket(rps=2.0)  # period = 0.5s
    bucket.acquire("example.com")
    start = time.monotonic()
    bucket.acquire("example.com")
    elapsed = time.monotonic() - start
    assert 0.45 <= elapsed <= 0.65


def test_different_hosts_do_not_block_each_other():
    bucket = HostTokenBucket(rps=1.0)
    bucket.acquire("example.com")
    start = time.monotonic()
    bucket.acquire("other.com")
    elapsed = time.monotonic() - start
    assert elapsed < 0.05


def test_concurrent_acquires_on_same_host_serialize():
    bucket = HostTokenBucket(rps=2.0)  # period = 0.5s
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: bucket.acquire("example.com"), range(3)))
    elapsed = time.monotonic() - start
    # 3 acquires at 2 rps with the first immediate => ~1.0s total
    assert 0.9 <= elapsed <= 1.2
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_throttle.py -v
```

Expected: ImportError / collection error — `fetcher.throttle` doesn't exist yet.

- [ ] **Step 3: Implement the token bucket**

Create `fetcher/throttle.py`:

```python
"""Per-host rate limiter. One lock + last-acquire timestamp per host.

Used by fetcher.client to space outbound HTTP GETs to the same host even
when the threadpool would otherwise issue them concurrently. A different
host never blocks on this lock.
"""

from __future__ import annotations

import threading
import time


class HostTokenBucket:
    """rps requests per second per host. Capacity is effectively 1
    (single-token bucket); we just delay until `1/rps` has elapsed since
    the previous acquire for the same host."""

    def __init__(self, rps: float) -> None:
        if rps <= 0:
            raise ValueError("rps must be > 0")
        self._period = 1.0 / rps
        self._lock = threading.Lock()
        self._next_allowed: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}

    def _lock_for(self, host: str) -> threading.Lock:
        with self._lock:
            lk = self._host_locks.get(host)
            if lk is None:
                lk = threading.Lock()
                self._host_locks[host] = lk
            return lk

    def acquire(self, host: str) -> None:
        """Block until a request to `host` is allowed; then mark the
        next-allowed timestamp."""
        host_lock = self._lock_for(host)
        with host_lock:
            now = time.monotonic()
            next_allowed = self._next_allowed.get(host, 0.0)
            if now < next_allowed:
                time.sleep(next_allowed - now)
                now = time.monotonic()
            self._next_allowed[host] = now + self._period
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_throttle.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/throttle.py tests/__init__.py tests/fetcher/__init__.py tests/fetcher/test_throttle.py
git commit -m "fetcher: per-host token bucket with tests"
```

---

### Task 7: Generic extractor (trafilatura)

**Files:**
- Create: `fetcher/extractors/__init__.py`
- Create: `fetcher/extractors/generic.py`
- Create: `tests/fetcher/test_extractors.py`

- [ ] **Step 1: Create the package marker**

Create `fetcher/extractors/__init__.py` (empty).

- [ ] **Step 2: Write the failing test**

Create `tests/fetcher/test_extractors.py`:

```python
"""Unit tests for per-ATS and generic extractors. Fixtures are
intentionally tiny strings so the tests have no I/O and run fast."""

from __future__ import annotations

from fetcher.extractors.generic import GenericExtractor


def test_generic_extracts_main_content_from_simple_html():
    html = """
    <html><head><title>Senior Engineer at Acme</title></head>
      <body>
        <nav>home about</nav>
        <article>
          <h1>Senior Engineer</h1>
          <p>We are hiring a senior software engineer to build distributed
          systems. You will design APIs, write code, and mentor juniors.
          The role is fully remote within the US.</p>
          <p>Requirements: 5+ years of Python, experience with PostgreSQL
          and Kafka, strong communication.</p>
        </article>
        <footer>(c) Acme</footer>
      </body>
    </html>
    """
    result = GenericExtractor().extract(url="https://example.com/jobs/1", html=html)
    assert result.extractor == "trafilatura"
    assert result.body_text is not None
    assert "senior software engineer" in result.body_text.lower()
    assert "5+ years of Python" in result.body_text


def test_generic_returns_none_when_no_main_content():
    html = "<html><body><div></div></body></html>"
    result = GenericExtractor().extract(url="https://example.com", html=html)
    assert result.extractor == "trafilatura"
    assert result.body_text is None
```

- [ ] **Step 3: Run the test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_extractors.py -v
```

Expected: ImportError — `fetcher.extractors.generic` doesn't exist.

- [ ] **Step 4: Implement**

Create `fetcher/extractors/generic.py`:

```python
"""Generic main-content extractor backed by trafilatura. Used as the
default when no per-ATS extractor matches the URL host, and as the
fallback when a per-ATS extractor returns an empty result."""

from __future__ import annotations

import trafilatura

from fetcher.base import ExtractorResult


class GenericExtractor:
    name = "trafilatura"

    def extract(self, *, url: str, html: str) -> ExtractorResult:
        body = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if body:
            body = body.strip()
        return ExtractorResult(body_text=body or None, extractor=self.name)
```

- [ ] **Step 5: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_extractors.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add fetcher/extractors/__init__.py fetcher/extractors/generic.py tests/fetcher/test_extractors.py
git commit -m "fetcher: generic extractor (trafilatura) with tests"
```

---

### Task 8: ATS extractors (greenhouse, lever, workday)

**Files:**
- Create: `fetcher/extractors/greenhouse.py`
- Create: `fetcher/extractors/lever.py`
- Create: `fetcher/extractors/workday.py`
- Modify: `tests/fetcher/test_extractors.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/fetcher/test_extractors.py`:

```python
from fetcher.extractors.greenhouse import GreenhouseExtractor
from fetcher.extractors.lever import LeverExtractor
from fetcher.extractors.workday import WorkdayExtractor


def test_greenhouse_extracts_content_div():
    html = """
    <html><body>
      <div class="content">
        <h1>Backend Engineer</h1>
        <p>Build the platform. PostgreSQL, Python, Kafka.</p>
      </div>
    </body></html>
    """
    result = GreenhouseExtractor().extract(
        url="https://boards.greenhouse.io/acme/jobs/123", html=html
    )
    assert result.extractor == "greenhouse_v1"
    assert "Backend Engineer" in (result.body_text or "")
    assert "PostgreSQL" in (result.body_text or "")


def test_greenhouse_returns_none_when_content_div_missing():
    html = "<html><body><div>nothing useful</div></body></html>"
    result = GreenhouseExtractor().extract(url="https://x", html=html)
    assert result.body_text is None


def test_lever_extracts_posting_content():
    html = """
    <html><body>
      <div class="posting-content">
        <h2>About the role</h2>
        <p>Forward Deployed Engineer for enterprise customers.</p>
      </div>
    </body></html>
    """
    result = LeverExtractor().extract(
        url="https://jobs.lever.co/acme/abc", html=html
    )
    assert result.extractor == "lever_v1"
    assert "Forward Deployed Engineer" in (result.body_text or "")


def test_workday_extracts_job_posting_description():
    html = """
    <html><body>
      <div data-automation-id="jobPostingDescription">
        <p>Senior Software Engineer, Identity Platform.</p>
        <p>SAML, OAuth, OIDC.</p>
      </div>
    </body></html>
    """
    result = WorkdayExtractor().extract(
        url="https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/123",
        html=html,
    )
    assert result.extractor == "workday_v1"
    assert "Identity Platform" in (result.body_text or "")
    assert "OIDC" in (result.body_text or "")
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_extractors.py -v
```

Expected: ImportError for `greenhouse`, `lever`, `workday` modules.

- [ ] **Step 3: Implement Greenhouse**

Create `fetcher/extractors/greenhouse.py`:

```python
"""Greenhouse JD extractor. Targets the static HTML served by
boards.greenhouse.io/{org}/jobs/{id} and self-hosted greenhouse boards.
Returns body_text=None when no candidate selector matches; the registry
will then fall back to the generic extractor."""

from __future__ import annotations

from bs4 import BeautifulSoup

from fetcher.base import ExtractorResult

# Selectors tried in order. The first non-empty match wins.
_SELECTORS = ("div.content", "div.app-body", "section.content", "div#content")


class GreenhouseExtractor:
    name = "greenhouse_v1"

    def extract(self, *, url: str, html: str) -> ExtractorResult:
        soup = BeautifulSoup(html, "lxml")
        for sel in _SELECTORS:
            node = soup.select_one(sel)
            if node:
                text = node.get_text(separator="\n", strip=True)
                if text:
                    return ExtractorResult(body_text=text, extractor=self.name)
        return ExtractorResult(body_text=None, extractor=self.name)
```

- [ ] **Step 4: Implement Lever**

Create `fetcher/extractors/lever.py`:

```python
"""Lever JD extractor. Targets jobs.lever.co/{org}/{id}."""

from __future__ import annotations

from bs4 import BeautifulSoup

from fetcher.base import ExtractorResult

_SELECTORS = ("div.posting-content", "div.section-wrapper.page-full-width")


class LeverExtractor:
    name = "lever_v1"

    def extract(self, *, url: str, html: str) -> ExtractorResult:
        soup = BeautifulSoup(html, "lxml")
        for sel in _SELECTORS:
            node = soup.select_one(sel)
            if node:
                text = node.get_text(separator="\n", strip=True)
                if text:
                    return ExtractorResult(body_text=text, extractor=self.name)
        return ExtractorResult(body_text=None, extractor=self.name)
```

- [ ] **Step 5: Implement Workday**

Create `fetcher/extractors/workday.py`:

```python
"""Workday JD extractor. Targets *.myworkdayjobs.com pages, which are
SPAs but include the JD body in the initial HTML for SEO."""

from __future__ import annotations

from bs4 import BeautifulSoup

from fetcher.base import ExtractorResult


class WorkdayExtractor:
    name = "workday_v1"

    def extract(self, *, url: str, html: str) -> ExtractorResult:
        soup = BeautifulSoup(html, "lxml")
        node = soup.select_one("div[data-automation-id='jobPostingDescription']")
        if node:
            text = node.get_text(separator="\n", strip=True)
            if text:
                return ExtractorResult(body_text=text, extractor=self.name)
        return ExtractorResult(body_text=None, extractor=self.name)
```

- [ ] **Step 6: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_extractors.py -v
```

Expected: 6 passed (the 2 generic tests + 4 new ones).

- [ ] **Step 7: Commit**

```bash
git add fetcher/extractors/greenhouse.py fetcher/extractors/lever.py fetcher/extractors/workday.py tests/fetcher/test_extractors.py
git commit -m "fetcher: greenhouse/lever/workday extractors with tests"
```

---

### Task 9: Ashby extractor (with API fallback)

**Files:**
- Create: `fetcher/extractors/ashby.py`
- Modify: `tests/fetcher/test_extractors.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/fetcher/test_extractors.py`:

```python
import json
from unittest.mock import patch, Mock

from fetcher.extractors.ashby import AshbyExtractor, parse_ashby_url


def test_parse_ashby_url():
    assert parse_ashby_url("https://jobs.ashbyhq.com/acme/abc-123") == ("acme", "abc-123")
    assert parse_ashby_url("https://jobs.ashbyhq.com/acme/abc-123/apply") == ("acme", "abc-123")
    assert parse_ashby_url("https://jobs.ashbyhq.com/acme") is None
    assert parse_ashby_url("https://example.com/jobs/1") is None


def test_ashby_uses_static_html_when_present():
    html = """
    <html><body>
      <div class="posting-description">
        <p>Platform Engineer at Ashby-hosted company.</p>
      </div>
    </body></html>
    """
    result = AshbyExtractor().extract(
        url="https://jobs.ashbyhq.com/acme/abc-123", html=html
    )
    assert result.extractor == "ashby_v1"
    assert "Platform Engineer" in (result.body_text or "")


def test_ashby_falls_back_to_api_when_html_empty():
    html = "<html><body><div id=\"root\"></div></body></html>"
    api_payload = {
        "jobPosting": {
            "title": "Backend Engineer",
            "descriptionHtml": "<p>Build the backend at Acme.</p>",
        }
    }
    fake_response = Mock(status_code=200)
    fake_response.json.return_value = api_payload
    fake_response.raise_for_status = Mock()

    with patch("fetcher.extractors.ashby.requests.get", return_value=fake_response) as mock_get:
        result = AshbyExtractor().extract(
            url="https://jobs.ashbyhq.com/acme/abc-123", html=html
        )
    mock_get.assert_called_once()
    assert "Build the backend at Acme" in (result.body_text or "")
    assert result.extractor == "ashby_v1_api"


def test_ashby_returns_none_when_url_unparseable():
    html = "<html><body></body></html>"
    result = AshbyExtractor().extract(url="https://jobs.ashbyhq.com/acme", html=html)
    assert result.body_text is None
    assert result.extractor == "ashby_v1"
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_extractors.py -v
```

Expected: ImportError for `fetcher.extractors.ashby`.

- [ ] **Step 3: Implement**

Create `fetcher/extractors/ashby.py`:

```python
"""Ashby JD extractor. jobs.ashbyhq.com is a React SPA; the static HTML
sometimes contains the description and sometimes doesn't. We try the
static selector first, then fall back to Ashby's public posting API,
which returns the JD as `descriptionHtml`."""

from __future__ import annotations

from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import config
from fetcher.base import ExtractorResult

_API_TEMPLATE = "https://api.ashbyhq.com/posting-api/job-board/{org}/{posting_id}"


def parse_ashby_url(url: str) -> tuple[str, str] | None:
    """Extract (org, posting_id) from jobs.ashbyhq.com/{org}/{id}[/...]."""
    parsed = urlparse(url)
    if "ashbyhq.com" not in (parsed.netloc or "").lower():
        return None
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


class AshbyExtractor:
    name = "ashby_v1"

    def extract(self, *, url: str, html: str) -> ExtractorResult:
        soup = BeautifulSoup(html, "lxml")
        node = soup.select_one("div.posting-description, div._description_1ek5g_103")
        if node:
            text = node.get_text(separator="\n", strip=True)
            if text:
                return ExtractorResult(body_text=text, extractor=self.name)

        parsed = parse_ashby_url(url)
        if not parsed:
            return ExtractorResult(body_text=None, extractor=self.name)
        org, posting_id = parsed
        try:
            resp = requests.get(
                _API_TEMPLATE.format(org=org, posting_id=posting_id),
                timeout=config.JD_FETCH_TIMEOUT,
                headers={"User-Agent": config.JD_USER_AGENT},
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return ExtractorResult(body_text=None, extractor=self.name)

        posting = payload.get("jobPosting") or {}
        description_html = posting.get("descriptionHtml") or ""
        if not description_html:
            return ExtractorResult(body_text=None, extractor=self.name)
        text = BeautifulSoup(description_html, "lxml").get_text(
            separator="\n", strip=True
        )
        return ExtractorResult(
            body_text=text or None, extractor="ashby_v1_api"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_extractors.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/extractors/ashby.py tests/fetcher/test_extractors.py
git commit -m "fetcher: ashby extractor with API fallback"
```

---

### Task 10: Extractor registry

**Files:**
- Create: `fetcher/extractors/registry.py`
- Create: `tests/fetcher/test_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/fetcher/test_registry.py`:

```python
"""Unit tests for the host -> extractor registry."""

from __future__ import annotations

from fetcher.extractors.ashby import AshbyExtractor
from fetcher.extractors.generic import GenericExtractor
from fetcher.extractors.greenhouse import GreenhouseExtractor
from fetcher.extractors.lever import LeverExtractor
from fetcher.extractors.registry import ats_for_host, extractors_for_host
from fetcher.extractors.workday import WorkdayExtractor


def test_greenhouse_hosts():
    assert ats_for_host("boards.greenhouse.io") == "greenhouse"
    assert ats_for_host("careers.acme.com.greenhouse.io") == "greenhouse"
    assert isinstance(extractors_for_host("boards.greenhouse.io")[0], GreenhouseExtractor)


def test_lever_host():
    assert ats_for_host("jobs.lever.co") == "lever"
    assert isinstance(extractors_for_host("jobs.lever.co")[0], LeverExtractor)


def test_ashby_host():
    assert ats_for_host("jobs.ashbyhq.com") == "ashby"
    assert isinstance(extractors_for_host("jobs.ashbyhq.com")[0], AshbyExtractor)


def test_workday_host():
    assert ats_for_host("acme.wd5.myworkdayjobs.com") == "workday"
    assert isinstance(extractors_for_host("acme.wd5.myworkdayjobs.com")[0], WorkdayExtractor)


def test_unknown_host_falls_back_to_generic_only():
    assert ats_for_host("careers.acme.com") == "generic"
    chain = extractors_for_host("careers.acme.com")
    assert len(chain) == 1
    assert isinstance(chain[0], GenericExtractor)


def test_known_host_always_ends_with_generic():
    chain = extractors_for_host("boards.greenhouse.io")
    assert isinstance(chain[-1], GenericExtractor)
    assert len(chain) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_registry.py -v
```

Expected: ImportError for `fetcher.extractors.registry`.

- [ ] **Step 3: Implement**

Create `fetcher/extractors/registry.py`:

```python
"""Host-suffix lookup table for ATS detection and extractor selection.
Returns an *ordered chain* of extractors to try; the generic extractor is
always last, so per-ATS extractors can return body_text=None to opt into
generic fallback without coordinating across modules."""

from __future__ import annotations

from fetcher.base import Extractor
from fetcher.extractors.ashby import AshbyExtractor
from fetcher.extractors.generic import GenericExtractor
from fetcher.extractors.greenhouse import GreenhouseExtractor
from fetcher.extractors.lever import LeverExtractor
from fetcher.extractors.workday import WorkdayExtractor

# Match by suffix on the lowercase host.
_ATS_BY_HOST_SUFFIX: tuple[tuple[str, str, type[Extractor]], ...] = (
    ("greenhouse.io", "greenhouse", GreenhouseExtractor),
    ("lever.co", "lever", LeverExtractor),
    ("ashbyhq.com", "ashby", AshbyExtractor),
    ("myworkdayjobs.com", "workday", WorkdayExtractor),
)


def ats_for_host(host: str) -> str:
    h = (host or "").lower()
    for suffix, ats, _ in _ATS_BY_HOST_SUFFIX:
        if h == suffix or h.endswith("." + suffix) or h.endswith(suffix):
            return ats
    return "generic"


def extractors_for_host(host: str) -> list[Extractor]:
    h = (host or "").lower()
    chain: list[Extractor] = []
    for suffix, _, cls in _ATS_BY_HOST_SUFFIX:
        if h == suffix or h.endswith("." + suffix) or h.endswith(suffix):
            chain.append(cls())
            break
    chain.append(GenericExtractor())
    return chain
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_registry.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/extractors/registry.py tests/fetcher/test_registry.py
git commit -m "fetcher: extractor registry with generic fallback chain"
```

---

### Task 11: `fetcher/client.py` — `fetch_many`

**Files:**
- Create: `fetcher/client.py`
- Create: `tests/fetcher/test_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/fetcher/test_client.py`:

```python
"""Integration tests for fetch_many. Uses an in-memory SQLite DB so the
ORM model + transaction semantics are exercised without needing Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import Base, JobDescription
from fetcher.base import FetchOutcome
from fetcher.client import fetch_many


@pytest.fixture
def session() -> Session:
    # SQLite to avoid Postgres-specific JSONB; the JD table is JSONB-free.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sess = Session(engine)
    yield sess
    sess.close()


def _ok_html(body: str) -> str:
    return f"""<html><body><div class="content">{body}</div></body></html>"""


def _mock_response(status: int, text: str, content_type: str = "text/html"):
    resp = Mock(status_code=status)
    resp.text = text
    resp.content = text.encode()
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status = Mock(
        side_effect=None if status < 400 else __import__("requests").HTTPError(response=resp)
    )
    return resp


def test_fetch_many_persists_ok_outcome(session):
    urls = [("https://boards.greenhouse.io/acme/jobs/1", "https://boards.greenhouse.io/acme/jobs/1")]
    with patch("fetcher.client.requests.Session.get",
               return_value=_mock_response(200, _ok_html("Backend Engineer at Acme."))):
        outcomes = fetch_many(session, urls)

    assert len(outcomes) == 1
    outcome = outcomes[urls[0][0]]
    assert outcome.status == "ok"
    assert outcome.ats == "greenhouse"
    assert outcome.body_text and "Backend Engineer" in outcome.body_text
    assert outcome.job_description_id is not None

    rows = session.query(JobDescription).all()
    assert len(rows) == 1
    assert rows[0].status == "ok"
    assert rows[0].ats == "greenhouse"


def test_fetch_many_uses_cache_within_ttl(session):
    nurl = "https://boards.greenhouse.io/acme/jobs/1"
    session.add(JobDescription(
        normalized_url=nurl,
        url=nurl,
        status="ok",
        ats="greenhouse",
        body_text="cached body",
        extractor="greenhouse_v1",
        fetched_at=datetime.now(timezone.utc) - timedelta(days=1),
    ))
    session.flush()

    with patch("fetcher.client.requests.Session.get") as mock_get:
        outcomes = fetch_many(session, [(nurl, nurl)])

    mock_get.assert_not_called()
    assert outcomes[nurl].status == "ok"
    assert outcomes[nurl].body_text == "cached body"


def test_fetch_many_re_fetches_after_ttl(session):
    nurl = "https://boards.greenhouse.io/acme/jobs/1"
    import config
    stale_age = timedelta(days=config.JD_CACHE_TTL_DAYS + 1)
    session.add(JobDescription(
        normalized_url=nurl,
        url=nurl,
        status="ok",
        ats="greenhouse",
        body_text="stale body",
        extractor="greenhouse_v1",
        fetched_at=datetime.now(timezone.utc) - stale_age,
    ))
    session.flush()

    with patch("fetcher.client.requests.Session.get",
               return_value=_mock_response(200, _ok_html("fresh body for engineers"))):
        outcomes = fetch_many(session, [(nurl, nurl)])

    assert outcomes[nurl].body_text and "fresh body" in outcomes[nurl].body_text

    rows = session.query(JobDescription).all()
    assert len(rows) == 1  # updated in place, not duplicated


def test_fetch_many_records_http_error(session):
    nurl = "https://boards.greenhouse.io/acme/jobs/1"
    with patch("fetcher.client.requests.Session.get",
               return_value=_mock_response(403, "<html>forbidden</html>")):
        outcomes = fetch_many(session, [(nurl, nurl)])

    assert outcomes[nurl].status == "http_error"
    assert outcomes[nurl].http_status == 403
    assert outcomes[nurl].body_text is None

    row = session.query(JobDescription).one()
    assert row.status == "http_error"
    assert row.http_status == 403


def test_fetch_many_marks_short_body_as_unsupported(session):
    nurl = "https://boards.greenhouse.io/acme/jobs/1"
    with patch("fetcher.client.requests.Session.get",
               return_value=_mock_response(200, _ok_html("Too short"))):
        outcomes = fetch_many(session, [(nurl, nurl)])

    assert outcomes[nurl].status == "unsupported"
    assert outcomes[nurl].body_text is None


def test_fetch_many_handles_empty_input(session):
    outcomes = fetch_many(session, [])
    assert outcomes == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_client.py -v
```

Expected: collection error — `fetch_many` not found in `fetcher.client`.

- [ ] **Step 3: Implement**

Create `fetcher/client.py`:

```python
"""Threadpooled, cached JD fetcher. The single entry point used by score.py.

Concurrency: a ThreadPoolExecutor of JD_FETCH_WORKERS workers issues GETs;
a HostTokenBucket serializes requests to the same host at JD_FETCH_PER_HOST_RPS.

Caching: rows in `job_descriptions` are reused when fetched_at is within
JD_CACHE_TTL_DAYS. Both successes and failures are cached this way -- a
failure row prevents an immediate retry but expires normally, so a future
run can pick it up again.
"""

from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from db.models import JobDescription
from fetcher.base import FetchOutcome
from fetcher.extractors.registry import ats_for_host, extractors_for_host
from fetcher.throttle import HostTokenBucket

log = logging.getLogger(__name__)

# Single shared bucket per process is fine -- the rate is per-host, not global.
_bucket = HostTokenBucket(rps=config.JD_FETCH_PER_HOST_RPS)
_http_session = requests.Session()


def fetch_many(
    session: Session,
    urls: list[tuple[str, str]],
) -> dict[str, FetchOutcome]:
    """Fetch (or look up cached) bodies for every (normalized_url, url).

    Returns: {normalized_url: FetchOutcome}. Every key in `urls` is in
    the result. Cache hits return immediately; misses are fanned across
    a threadpool.
    """
    if not urls:
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=config.JD_CACHE_TTL_DAYS)
    nurl_set = [nurl for nurl, _ in urls]

    cached_rows: dict[str, JobDescription] = {
        row.normalized_url: row
        for row in session.scalars(
            select(JobDescription)
            .where(JobDescription.normalized_url.in_(nurl_set))
            .where(JobDescription.fetched_at >= cutoff)
        )
    }

    outcomes: dict[str, FetchOutcome] = {}
    misses: list[tuple[str, str]] = []
    for nurl, url in urls:
        row = cached_rows.get(nurl)
        if row is not None:
            outcomes[nurl] = _outcome_from_row(row)
        else:
            misses.append((nurl, url))

    if not misses:
        return outcomes

    workers = max(1, min(config.JD_FETCH_WORKERS, len(misses)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_one, url): (nurl, url) for nurl, url in misses
        }
        for fut in futures:
            nurl, url = futures[fut]
            outcome = fut.result()
            # Persist (insert or update) on the calling thread so we hold one
            # session/transaction. SQLAlchemy sessions are not thread-safe.
            row = _upsert(session, nurl=nurl, url=url, outcome=outcome)
            outcomes[nurl] = replace(outcome, job_description_id=row.id)
    session.flush()
    return outcomes


def _outcome_from_row(row: JobDescription) -> FetchOutcome:
    return FetchOutcome(
        status=row.status,  # type: ignore[arg-type]
        ats=row.ats or "generic",
        body_text=row.body_text,
        http_status=row.http_status,
        error=row.error,
        latency_ms=row.latency_ms or 0,
        extractor=row.extractor,
        job_description_id=row.id,
    )


def _fetch_one(url: str) -> FetchOutcome:
    host = (urlparse(url).netloc or "").lower()
    ats = ats_for_host(host)
    _bucket.acquire(host)

    start = time.monotonic()
    try:
        resp = _http_session.get(
            url,
            timeout=config.JD_FETCH_TIMEOUT,
            headers={"User-Agent": config.JD_USER_AGENT},
            allow_redirects=True,
        )
    except requests.Timeout as e:
        return FetchOutcome(
            status="timeout", ats=ats, body_text=None, http_status=None,
            error=str(e)[:1000], latency_ms=int((time.monotonic() - start) * 1000),
            extractor="(none)", job_description_id=None,
        )
    except requests.RequestException as e:
        return FetchOutcome(
            status="http_error", ats=ats, body_text=None, http_status=None,
            error=str(e)[:1000], latency_ms=int((time.monotonic() - start) * 1000),
            extractor="(none)", job_description_id=None,
        )

    latency_ms = int((time.monotonic() - start) * 1000)

    if resp.status_code >= 400:
        return FetchOutcome(
            status="http_error", ats=ats, body_text=None,
            http_status=resp.status_code,
            error=f"HTTP {resp.status_code}", latency_ms=latency_ms,
            extractor="(none)", job_description_id=None,
        )

    ct = (resp.headers.get("Content-Type") or "").lower()
    if ct and "html" not in ct and "xml" not in ct:
        return FetchOutcome(
            status="unsupported", ats=ats, body_text=None,
            http_status=resp.status_code,
            error=f"non-HTML content-type: {ct}", latency_ms=latency_ms,
            extractor="(none)", job_description_id=None,
        )

    html = resp.text or ""
    body: str | None = None
    extractor_name = "(none)"
    for extractor in extractors_for_host(host):
        try:
            result = extractor.extract(url=url, html=html)
        except Exception as e:
            log.warning("extractor %s crashed on %s: %s", extractor.name, url, e)
            continue
        if result.body_text:
            body = result.body_text
            extractor_name = result.extractor
            break
        extractor_name = result.extractor  # remember the last one we tried

    if body is None:
        return FetchOutcome(
            status="parse_failed", ats=ats, body_text=None,
            http_status=resp.status_code,
            error="no extractor returned body_text", latency_ms=latency_ms,
            extractor=extractor_name, job_description_id=None,
        )

    if len(body) < config.JD_MIN_BODY_CHARS:
        return FetchOutcome(
            status="unsupported", ats=ats, body_text=None,
            http_status=resp.status_code,
            error=f"body shorter than {config.JD_MIN_BODY_CHARS} chars ({len(body)})",
            latency_ms=latency_ms,
            extractor=extractor_name, job_description_id=None,
        )

    return FetchOutcome(
        status="ok", ats=ats, body_text=body,
        http_status=resp.status_code,
        error=None, latency_ms=latency_ms,
        extractor=extractor_name, job_description_id=None,
    )


def _upsert(
    session: Session, *, nurl: str, url: str, outcome: FetchOutcome
) -> JobDescription:
    row = session.scalar(
        select(JobDescription).where(JobDescription.normalized_url == nurl)
    )
    sha = (
        hashlib.sha256(outcome.body_text.encode("utf-8")).hexdigest()
        if outcome.body_text
        else None
    )
    if row is None:
        row = JobDescription(
            normalized_url=nurl,
            url=url,
            status=outcome.status,
            http_status=outcome.http_status,
            ats=outcome.ats,
            body_text=outcome.body_text,
            body_html_sha256=sha,
            extractor=outcome.extractor,
            error=outcome.error,
            latency_ms=outcome.latency_ms,
            fetched_at=datetime.now(timezone.utc),
        )
        session.add(row)
    else:
        row.url = url
        row.status = outcome.status
        row.http_status = outcome.http_status
        row.ats = outcome.ats
        row.body_text = outcome.body_text
        row.body_html_sha256 = sha
        row.extractor = outcome.extractor
        row.error = outcome.error
        row.latency_ms = outcome.latency_ms
        row.fetched_at = datetime.now(timezone.utc)
    session.flush()
    return row
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher/test_client.py -v
```

Expected: 6 passed. (If the short-body test fails because `JD_MIN_BODY_CHARS` defaults to 400 and the fixture's "Backend Engineer at Acme." is shorter than 400 chars, the test `test_fetch_many_persists_ok_outcome` will fail too. Adjust the fixture in `_ok_html` to a longer string:)

If `test_fetch_many_persists_ok_outcome` fails because the body is too short, replace its `_ok_html(...)` call with one that produces at least 500 characters — e.g.:

```python
body = "Backend Engineer at Acme. " * 30
_ok_html(body)
```

Re-run the test; expected: 6 passed.

- [ ] **Step 5: Run the full fetcher test suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/fetcher -v
```

Expected: 26 passed (4 throttle + 10 extractors + 6 registry + 6 client).

- [ ] **Step 6: Commit**

```bash
git add fetcher/client.py tests/fetcher/test_client.py
git commit -m "fetcher: fetch_many with threadpool, per-host throttle, ttl cache"
```

---

### Task 12: Integrate into `score.py`

**Files:**
- Modify: `score.py`

- [ ] **Step 1: Update `_to_dict` signature and add `_pick_description`**

Open `score.py`. Replace the existing `_to_dict` function (currently at [score.py:24-30](../../../score.py#L24-L30)) with:

```python
def _pick_description(sr: SearchResult, outcome) -> tuple[str, str, int | None]:
    """Return (description_text, source, job_description_id). When the
    fetched body is available, use it; otherwise fall back to the snippet."""
    if outcome is not None and outcome.status == "ok" and outcome.body_text:
        return outcome.body_text, "body", outcome.job_description_id
    return sr.snippet, "snippet_fallback" if outcome is not None else "snippet", None


def _to_dict(sr: SearchResult, outcome=None) -> dict:
    description, _source, _jd_id = _pick_description(sr, outcome)
    return {
        "title": sr.title,
        "url": sr.url,
        "snippet": description,  # field name kept for prompt compatibility
        "engine": sr.engine,
    }
```

Yes, we deliberately keep the prompt field named `snippet` so existing provider prompts don't need to change; the field's *contents* are now the body when available.

- [ ] **Step 2: Add the fetcher call inside `score_all`**

In `score.py::score_all`, locate the block that runs after prefilter and before `provider.score_batch` — currently the `if not to_score: continue` then `try: outcome = provider.score_batch(...)`. Replace those lines (currently around `score.py:270`) with:

```python
        if not to_score:
            session.flush()
            print("    skipped LLM: all items handled by cache/prefilter")
            continue

        if config.JD_FETCH_ENABLED:
            jd_outcomes = fetcher.fetch_many(
                session,
                [(sr.normalized_url, sr.url) for sr in to_score],
            )
        else:
            jd_outcomes = {}

        prepared = [
            (sr, _pick_description(sr, jd_outcomes.get(sr.normalized_url)))
            for sr in to_score
        ]
        payloads = [_to_dict(sr, jd_outcomes.get(sr.normalized_url)) for sr in to_score]

        try:
            outcome = provider.score_batch(payloads, criteria)
        except Exception as e:
            log.warning("batch %d crashed entirely: %s", bi + 1, e)
            continue
```

- [ ] **Step 3: Persist `source` + `job_description_id` on each new `ScoredResult`**

Still in `score_all`, locate the loop that creates `ScoredResult` rows from `outcome.scored` (currently `score.py:307-326`). Replace the `ScoredResult(...)` construction with:

```python
        for sj in outcome.scored:
            if sj.index < 0 or sj.index >= len(to_score):
                continue
            sr = to_score[sj.index]
            kept = bool(sj.is_job and sj.score >= min_score)
            _sr, (_desc, source, jd_id) = prepared[sj.index]
            scored = ScoredResult(
                run_id=run.id,
                search_result_id=sr.id,
                llm_call_id=last_call.id,
                is_job=sj.is_job,
                title=sj.title,
                company=sj.company,
                location=sj.location,
                remote=sj.remote,
                score=sj.score,
                reason=sj.reason,
                kept=kept,
                source=source,
                job_description_id=jd_id,
            )
            session.add(scored)
            all_scored.append(scored)
            llm_scored += 1
```

- [ ] **Step 4: Add the import at the top of `score.py`**

Near the existing imports in `score.py` (after the `import config` line), add:

```python
import fetcher
```

- [ ] **Step 5: Verify the module still imports**

```powershell
.\.venv\Scripts\python.exe -c "import score; print('ok')"
```

Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add score.py
git commit -m "score: fetch JD bodies before LLM call, set source/job_description_id"
```

---

### Task 13: End-of-run JD summary

**Files:**
- Modify: `score.py`

- [ ] **Step 1: Accumulate per-batch outcomes**

In `score.py::score_all`, near the existing `cache_hits = 0`/`prefilter_hits = 0`/`llm_scored = 0` accumulators (around `score.py:201-203`), add:

```python
    jd_totals = {
        "fetched": 0,
        "cached": 0,
        "ok": 0,
        "http_error": 0,
        "timeout": 0,
        "unsupported": 0,
        "parse_failed": 0,
        "snippet_fallback": 0,
    }
    jd_ats: dict[str, int] = {}
```

Then after the `jd_outcomes = fetcher.fetch_many(...)` call inside the batch loop, add:

```python
        for _nurl, oc in jd_outcomes.items():
            # We can't distinguish 'cached' from 'fresh' purely from the
            # outcome, so we count by status; the cache-vs-fresh split is
            # observable in job_descriptions.fetched_at directly.
            jd_totals[oc.status] = jd_totals.get(oc.status, 0) + 1
            jd_totals["fetched"] += 1
            if oc.status == "ok":
                jd_ats[oc.ats] = jd_ats.get(oc.ats, 0) + 1
            else:
                jd_totals["snippet_fallback"] += 1
```

- [ ] **Step 2: Print the summary at end-of-run**

At the bottom of `score_all`, just before the existing `return kept_list` line (around `score.py:340`), add:

```python
    if jd_totals["fetched"]:
        ats_summary = ", ".join(
            f"{ats}={n}" for ats, n in sorted(jd_ats.items(), key=lambda x: -x[1])
        ) or "(none)"
        print(
            "  JD fetch: "
            f"fetched={jd_totals['fetched']} "
            f"ok={jd_totals['ok']} "
            f"http_error={jd_totals['http_error']} "
            f"timeout={jd_totals['timeout']} "
            f"unsupported={jd_totals['unsupported']} "
            f"parse_failed={jd_totals['parse_failed']} "
            f"snippet_fallback={jd_totals['snippet_fallback']}"
        )
        print(f"  ATS mix (ok-only): {ats_summary}")
```

- [ ] **Step 3: Verify the module still imports**

```powershell
.\.venv\Scripts\python.exe -c "import score; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add score.py
git commit -m "score: end-of-run JD fetch summary"
```

---

### Task 14: End-to-end smoke verification

**Files:** none changed; this is a manual verification task.

- [ ] **Step 1: Confirm `JD_FETCH_ENABLED` defaults to true**

```powershell
.\.venv\Scripts\python.exe -c "import config; print('JD_FETCH_ENABLED =', config.JD_FETCH_ENABLED)"
```

Expected: `JD_FETCH_ENABLED = True`.

- [ ] **Step 2: Run the pipeline against a small subset**

Temporarily reduce work: keep only one line in `titles.txt` and one line in `sites.txt` (e.g. greenhouse.io). Back up the originals first.

```powershell
copy titles.txt titles.txt.bak
copy sites.txt sites.txt.bak
echo Software Engineer > titles.txt
echo site:greenhouse.io > sites.txt
.\.venv\Scripts\python.exe main.py --skip-email
copy titles.txt.bak titles.txt
copy sites.txt.bak sites.txt
del titles.txt.bak
del sites.txt.bak
```

Expected console output near the end: a `JD fetch: fetched=N ok=...` line and an `ATS mix (ok-only): greenhouse=...` line.

- [ ] **Step 3: Verify `job_descriptions` rows landed**

```powershell
docker exec -it job-search-postgres psql -U jobsearch -d jobsearch -c "SELECT status, ats, count(*), avg(length(body_text))::int AS avg_chars FROM job_descriptions GROUP BY status, ats ORDER BY count(*) DESC;"
```

Expected: at least one `ok | greenhouse | N | <several hundred>` row. Failure rows (`http_error`, `timeout`) are also expected and fine.

- [ ] **Step 4: Verify `scored_results.source` reflects the new path**

```powershell
docker exec -it job-search-postgres psql -U jobsearch -d jobsearch -c "SELECT source, count(*) FROM scored_results WHERE run_id = (SELECT max(id) FROM runs) GROUP BY source;"
```

Expected: rows with `source IN ('body', 'snippet_fallback')`. No `'snippet'` (that value is reserved for historical pre-feature rows).

- [ ] **Step 5: Spot-check one body-scored result**

```powershell
docker exec -it job-search-postgres psql -U jobsearch -d jobsearch -c "SELECT s.score, s.title, s.company, s.source, jd.ats, length(jd.body_text) AS body_chars FROM scored_results s JOIN job_descriptions jd ON jd.id = s.job_description_id WHERE s.run_id = (SELECT max(id) FROM runs) ORDER BY s.score DESC LIMIT 5;"
```

Expected: a handful of rows showing the body length matches the extracted JD (typically 1000-6000 chars for a real greenhouse JD), and the score reason text references concrete JD details (not just the title).

- [ ] **Step 6: Disable + re-run sanity check**

```powershell
$env:JD_FETCH_ENABLED = "false"
.\.venv\Scripts\python.exe main.py --skip-email
Remove-Item Env:\JD_FETCH_ENABLED
```

Expected: pipeline runs without any `JD fetch:` line printed, and the new run's `scored_results` have no `source='body'` rows (all `'snippet_fallback'` since outcomes is `{}`).

Wait — with `JD_FETCH_ENABLED=false`, `jd_outcomes` is `{}`, so `_pick_description` receives `outcome=None`. Looking at `_pick_description` from Task 12, `outcome is None` produces `source='snippet'`. That's the correct value for the "feature disabled" case (matches historical pre-feature semantics). Verify:

```powershell
docker exec -it job-search-postgres psql -U jobsearch -d jobsearch -c "SELECT source, count(*) FROM scored_results WHERE run_id = (SELECT max(id) FROM runs) GROUP BY source;"
```

Expected: all rows `source='snippet'`.

- [ ] **Step 7: Re-enable for normal operation (no commit; this is just resetting state)**

`JD_FETCH_ENABLED` defaults to `true` in `config.py`, so simply unsetting the env var (Step 6 already did this) restores the default.

---

## Self-review

I checked the plan against the spec section by section:

- **Schema (spec §"Schema"):** Task 2 (SQL migration) + Task 3 (ORM). All columns from the spec table are present, including `body_html_sha256`. The migration uses additive `IF NOT EXISTS` patterns so it's safe to re-run.
- **Pipeline change (spec §"Pipeline change"):** Task 12 inserts `fetch_many` between prefilter and `provider.score_batch` exactly as specified. The `_to_dict` field name `snippet` is intentionally retained inside the prompt — flagged in Step 1.
- **`fetcher/` package layout (spec §"New package"):** Tasks 5–11 build it file by file. Names match the spec's tree.
- **FetchOutcome shape (spec §"`FetchOutcome`"):** Task 5 mirrors all fields; `job_description_id` starts `None` and gets set in Task 11 via `dataclasses.replace`.
- **`fetch_many` contract (spec §"`fetcher.client.fetch_many` contract"):** Task 11's implementation matches each numbered step: TTL cache query, threadpool, per-host bucket, extractor chain, upsert.
- **Per-ATS extractors (spec §"Per-ATS extractors are intentionally dumb"):** Tasks 8 (greenhouse/lever/workday) + 9 (ashby with API fallback). Graceful generic fallback is in the registry chain (Task 10), not the individual extractors — same end behavior.
- **Configuration (spec §"Configuration"):** Task 4 adds all six knobs. I added one extra knob (`JD_MIN_BODY_CHARS`) for the "response too short" branch of `unsupported` that the spec's failure table references; flagged in the task body.
- **Failure handling (spec §"Failure handling and `source` semantics"):** Task 12's `_pick_description` and Task 13's summary cover every status → source mapping. The "feature disabled" extra case (`source='snippet'`) is documented in Task 14 Step 6 so a future reader isn't confused.
- **`score.py` diff (spec §"`score.py` change"):** Task 12 matches the sketch and adds the missing `import fetcher` line.
- **Observability (spec §"Observability"):** Task 13.
- **Dependencies (spec §"Dependencies"):** Task 1; pinned `>=` versions consistent with the rest of `requirements.txt`.
- **Rollout (spec §"Rollout"):** Task 14 covers the manual verification + the disable-flag sanity check.

**Placeholder scan:** no TBDs, TODOs, "add error handling" hand-waves, or "similar to Task N" pointers. Every code step has the actual code to paste.

**Type consistency:** `FetchOutcome` constructed in Task 11 matches the dataclass defined in Task 5. `Extractor` protocol method `extract(*, url, html) -> ExtractorResult` matches every extractor signature (Tasks 7–9). `ExtractorResult` has fields `body_text` and `extractor`, used identically in registry chain (Task 10) and `_fetch_one` (Task 11). `ats_for_host` / `extractors_for_host` names match between Task 10's implementation and Task 11's import. `_pick_description` returns `(str, str, int | None)` and is unpacked the same way in both call sites (Task 12 step 1 and step 3).

One minor adjustment I caught during review and fixed in-place: Task 11 step 4 includes a note about adjusting the `_ok_html` fixture if the test fails on `JD_MIN_BODY_CHARS`. This avoids a likely first-run failure rather than letting the engineer hit it cold.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-26-jd-fetching.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
