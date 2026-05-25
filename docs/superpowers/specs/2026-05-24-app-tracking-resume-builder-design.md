# Application Tracking + Resume Builder — Design Spec

**Date:** 2026-05-24
**Status:** Approved
**Owner:** Sumit Gupta
**Implementation target:** Codex (this document is the brief)

---

## 1. Goal

Add two UI-driven features to the existing job-search pipeline:

1. **Application tracking** — every Claude-scored job is implicitly an "application"; user transitions it through statuses (`discovered → saved → applied → interview → offer | rejected | ghosted`) with free-text notes.
2. **Per-job resume builder** — one-click generation of a tailored LaTeX resume for a specific job, using the user's existing `resume_template.tex`. Generated `.tex` is previewed, downloadable, and persisted (every generation stored as a version row).

UI is a Next.js app in cyberpunk/glitch aesthetic. Backend is a thin FastAPI shim over the existing Postgres schema. The current Python search/score daemon is **untouched**.

---

## 2. Architecture

Monorepo, three processes, one Postgres.

```
python-web-job-search/                  (existing repo root)
├── main.py, search.py, score.py        (daemon — UNCHANGED)
├── db/models.py                        (extended: 4 cols + 1 table)
├── db/migrations_sql/
│   └── 2026-05-24_app_tracking.sql     (NEW: one-shot ALTER + CREATE)
├── api/                                (NEW: FastAPI HTTP layer)
│   ├── __init__.py
│   ├── main.py                         (app factory, CORS, route mounts)
│   ├── deps.py                         (DB session, auth dependency)
│   ├── auth.py                         (password check, cookie sign/verify)
│   ├── schemas.py                      (Pydantic request/response models)
│   ├── resume.py                       (template load + Claude tailoring call)
│   └── routes/
│       ├── auth.py                     (login/logout/me)
│       ├── applications.py             (list, get, patch)
│       ├── resumes.py                  (generate, list, get, download)
│       └── stats.py                    (dashboard counters)
├── web/                                (NEW: Next.js 15 App Router)
│   ├── app/
│   │   ├── layout.tsx                  (cyber wrapper: scanlines, grid, fonts)
│   │   ├── login/page.tsx
│   │   ├── (app)/                      (route group, auth-gated layout)
│   │   │   ├── layout.tsx              (nav bar, requires auth)
│   │   │   ├── page.tsx                (dashboard)
│   │   │   ├── jobs/page.tsx
│   │   │   ├── applications/page.tsx
│   │   │   └── applications/[id]/page.tsx
│   │   └── globals.css                 (cyber tokens, scanline keyframes, etc.)
│   ├── components/
│   │   ├── cyber/                      (CyberCard, CyberButton, GlitchHeading, etc.)
│   │   └── ui/                         (shadcn primitives, restyled to tokens)
│   ├── lib/
│   │   ├── api.ts                      (typed fetch wrapper)
│   │   ├── types.ts                    (TS types mirroring Pydantic schemas)
│   │   └── utils.ts
│   ├── middleware.ts                   (cookie auth guard for (app)/*)
│   ├── tailwind.config.ts              (cyber color tokens, font families)
│   ├── components.json                 (shadcn config)
│   ├── package.json
│   └── tsconfig.json
├── resume_template.tex                 (NEW: user's template — already provided)
├── docker-compose.yml                  (existing; web/api added later for VPS)
├── .env                                (existing; extended with APP_PASSWORD)
└── docs/superpowers/specs/             (this file)
```

**Why FastAPI shim instead of Next.js server actions calling DB directly:**
Keeps the Python pipeline as the single owner of business logic. Future surfaces (Telegram bot, mobile app) reuse the same API.

**Why monorepo:** one `git pull`, one Postgres, one `.env`. For a personal tool, separation tax > separation value.

**Process model in dev:**
```
docker compose up postgres            # existing
python main.py --daemon               # search/score (existing)
uvicorn api.main:app --reload         # API on :8000
cd web && pnpm dev                    # UI on :3000
```

CORS configured in FastAPI to allow `http://localhost:3000` in dev. Cookie set with `SameSite=Lax`.

---

## 3. Data Model Changes

All managed via the existing manual `docker exec psql` migration pattern (no Alembic baselining for this scope).

### 3.1 Extend `scored_results`

```sql
ALTER TABLE scored_results
  ADD COLUMN IF NOT EXISTS status            VARCHAR(20)  NOT NULL DEFAULT 'discovered',
  ADD COLUMN IF NOT EXISTS notes             TEXT,
  ADD COLUMN IF NOT EXISTS applied_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ  NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS ix_scored_results_status ON scored_results(status);
```

**Status state machine** (enforced in API layer, not DB):

```
discovered → saved → applied → interview → offer
                                         ↘ rejected
                                         ↘ ghosted    (suggested by UI when applied + 14d no movement)
```

7 valid values: `discovered | saved | applied | interview | offer | rejected | ghosted`.
`applied_at` is set when status moves to `applied` (kept after that, used for ghosted-suggestion timer + future analytics).
`status_updated_at` bumped by API on every status change.

### 3.2 New table: `resume_versions`

```sql
CREATE TABLE IF NOT EXISTS resume_versions (
  id                 SERIAL PRIMARY KEY,
  scored_result_id   INTEGER       NOT NULL REFERENCES scored_results(id) ON DELETE CASCADE,
  llm_call_id        INTEGER                REFERENCES llm_calls(id)      ON DELETE SET NULL,
  generated_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
  tex_content        TEXT          NOT NULL,
  model              VARCHAR(120)  NOT NULL,
  prompt_hash        VARCHAR(64)   NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_resume_versions_scored_result
  ON resume_versions(scored_result_id);
```

`prompt_hash` = SHA-256 of `(template_content || job_title || job_snippet || criteria_text)`. Used to suggest "you already have this version — open it or force regenerate?" in the UI.

### 3.3 SQLAlchemy model updates

In [db/models.py](db/models.py):

- Add to `ScoredResult` class: `status`, `notes`, `applied_at`, `status_updated_at` columns + `resume_versions` relationship.
- Add new `ResumeVersion` class with the schema above, bidirectional relationship to `ScoredResult` and optional FK to `LLMCall`.

The Python daemon does not read/write any of the new columns. They're for the API only.

### 3.4 Out of scope

- Separate `applications` table (every scored row IS an application).
- Status history audit table.
- File uploads (cover letter PDFs, etc.).
- Reminders / scheduled tasks (ghosted is *suggested* by UI, never auto-flipped).

---

## 4. API Surface

FastAPI, REST, JSON. All responses use Pydantic models defined in `api/schemas.py`. All `/api/*` routes except `/api/auth/login` require valid auth cookie (enforced by `Depends(require_auth)` from `api/deps.py`).

### 4.1 Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/login` | Body `{password}`. Sets `app_session` cookie. 401 on mismatch. |
| POST | `/api/auth/logout` | Clears cookie. |
| GET  | `/api/me` | `{ok: true}` if authed, else 401. Used by frontend boot to gate redirects. |
| GET  | `/api/applications` | Query: `status` (csv), `min_score`, `limit` (default 50), `offset`. Returns array of `Application`. |
| GET  | `/api/applications/{id}` | Single `ApplicationDetail` (joins SearchResult for url/title/snippet). |
| PATCH | `/api/applications/{id}` | Body: any subset of `{status, notes, applied_at}`. Bumps `status_updated_at`. Validates state machine. |
| GET  | `/api/applications/{id}/resumes` | List `ResumeVersion` rows (no `tex_content`) for the application, newest first. |
| POST | `/api/applications/{id}/resumes` | Generates new version via Claude. Query `?force=true` bypasses prompt_hash dedup. Returns full `ResumeVersion` including `tex_content`. |
| GET  | `/api/resumes/{version_id}` | Single `ResumeVersion` including `tex_content`. |
| GET  | `/api/resumes/{version_id}/download` | `Content-Type: application/x-tex`, `Content-Disposition: attachment; filename="<company>-<title>-v<n>.tex"`. |
| GET  | `/api/stats/overview` | Counts by status (all 7), counts by score bucket (60-69/70-79/80-89/90-100), totals. |
| GET  | `/api/stats/funnel` | Last 30 days timeline: applied/interview/offer per day. |

### 4.2 Auth

`api/auth.py`:
- `APP_PASSWORD` env required at startup; bail loudly if unset.
- `verify_password(plain)` — constant-time compare via `secrets.compare_digest`.
- `make_cookie()` — HMAC-SHA256 signs `(user_id="me", expires=now+30d)` with `APP_SECRET` env. Format `payload.signature`, base64-urlsafe.
- `parse_cookie(cookie)` — verify sig, check expiry, return claims or raise 401.
- `require_auth` FastAPI dependency reads `app_session` cookie via `Request`.

If `APP_SECRET` is unset, generate one on startup with `secrets.token_hex(32)` and warn — for dev. In prod, must be set explicitly (logout-everywhere is intentional otherwise).

### 4.3 Validation rules

State machine enforced server-side in PATCH:

```
discovered → {saved, applied, rejected, ghosted}    (skip-ahead allowed)
saved      → {applied, rejected, ghosted}
applied    → {interview, offer, rejected, ghosted}
interview  → {offer, rejected, ghosted}
offer      → {rejected}                              (you declined)
rejected   → {} (terminal; allow re-open back to applied if user explicitly re-applies)
ghosted    → {applied, interview, rejected}         (they finally responded)
```

Return 422 with `{detail: "cannot transition from X to Y"}` on invalid.

---

## 5. Resume Builder

### 5.1 Template handling

`resume_template.tex` lives at repo root (path overridable via `RESUME_TEMPLATE_PATH` env). Read at request time, not bundled into DB.

### 5.2 Tailoring prompt

`api/resume.py` builds a Claude message. Direct `anthropic.Anthropic()` SDK call (do not go through `providers/`; this is API-side only and doesn't need backend swapping).

**Model:** `claude-sonnet-4-6` (better instruction-following for structured LaTeX preservation than Haiku; ~$0.06/call).

**System prompt** (exact text, ship as a constant in `api/resume.py`):

```
You are a resume tailoring assistant. You will be given:
1. A complete LaTeX resume template (the candidate's base resume).
2. A target job posting (title, snippet, URL).
3. The candidate's profile/criteria.

Your job: return a tailored copy of the LaTeX resume that emphasizes the candidate's
fit for this specific job, by:
- Rewriting the Professional Summary paragraph to lead with the most-relevant keywords.
- Rewriting Experience bullets to emphasize tasks/skills the JD asks for. You may reorder
  bullets within a role. You may NOT add fictional experience. You MAY rephrase real bullets.
- Reordering the Skills buckets so most-relevant comes first. You MAY add or remove
  \textbf{} emphasis on specific skill items to align with JD keywords.

You MUST preserve verbatim:
- Every LaTeX command, package import, and preamble line.
- All custom commands (\resumeSubheading, \resumeItemA, \resumeSubItemWithLink, etc.).
- The Education section in full.
- Company names, job titles, and date ranges in Experience headings.
- The Projects section in full.
- The document's overall section order.

Output ONLY the complete tailored .tex file content, starting with \documentclass and
ending with \end{document}. No prose, no markdown, no code fences, no commentary.
```

**User message:** template content + JD + criteria, structured with clear delimiters.

### 5.3 Storage flow

1. POST `/api/applications/{id}/resumes` triggered.
2. Compute `prompt_hash`.
3. Unless `?force=true`, query `resume_versions WHERE scored_result_id=? AND prompt_hash=?` — if exists, return existing version (HTTP 200).
4. Call Claude. Persist returned `tex_content` to `resume_versions`. Also persist the LLM call to existing `llm_calls` table for audit, link via `llm_call_id`.
5. Return new `ResumeVersion` row.

### 5.4 Download filename

Format: `resume_<company-slug>_<role-slug>_v<n>.tex` where `<n>` is the user's nth version for that scored_result. Slugify aggressively (lowercase, ASCII, `-` separator, max 30 chars per slug).

---

## 6. UI Structure

### 6.1 Pages

| Route | Purpose |
|---|---|
| `/login` | Password form, redirects to `/` on success. |
| `/` | Dashboard: status funnel widget, recent activity, top-5 fresh discoveries (score ≥ 80, status=discovered). |
| `/jobs` | Raw feed of all `scored_results`. Filters: min score, status, site, date range. Each row links to `/applications/[id]`. |
| `/applications` | All non-`discovered` applications. Default view: list grouped by status. Filter chips per status. |
| `/applications/[id]` | Detail: job metadata, status changer, notes editor (auto-save), resume builder section. |

### 6.2 Application detail layout

Three vertical sections (top to bottom):

1. **Job header** — title, company (extracted from URL if available), score, url (external link), found-at timestamp. Glitch heading for the title.
2. **Status + notes** — status changer (cyber Select), `applied_at` date input (only when status=applied), notes textarea with debounced auto-save.
3. **Resume builder** — list of past versions (collapsed cards showing only generated_at + model). Big primary CTA: "GENERATE TAILORED RESUME". On click, calls POST, streams a loading state, shows the new version's `tex_content` in a code block with syntax highlighting + copy button + download button. If `prompt_hash` matches an existing version, modal: "Existing version found from <ago>. [Open] [Regenerate anyway]".

### 6.3 Core cyber components

In `web/components/cyber/`:

- `<CyberCard variant="default | terminal | holographic">` — chamfered, optional hover glow, optional terminal-header (3 dots).
- `<CyberButton variant="default | secondary | outline | ghost | glitch">` — uppercase, monospace, chamfered, neon glow on hover. Glitch variant has chromatic-aberration animation.
- `<CyberInput>` — `>` prefix prompt, accent color, neon focus ring.
- `<CyberSelect>` — Radix select styled with cyber tokens, dropdown with terminal aesthetic.
- `<CyberBadge variant="status-<value>">` — pills with status-specific accent (discovered=cyan, saved=green, applied=accent, interview=magenta, offer=accent+glow, rejected=destructive, ghosted=mutedForeground).
- `<GlitchHeading>` — `<h1>` with chromatic-aberration text-shadow + occasional glitch keyframe animation.
- `<StatPanel>` — number + label, chamfered border, neon-glow on accent number.
- `<ScanlineOverlay>` — fixed pseudo-element overlay on body, 5% opacity, rendered once in root layout.
- `<GridBackground>` — fixed background, low-opacity grid, rendered once in root layout.

### 6.4 shadcn baseline

Install: `card button input select badge dialog tabs toast` via shadcn CLI. Override tokens in `tailwind.config.ts` to point at cyberpunk colors (no `--background: white`; use `#0a0a0f`). Then `components/cyber/*` either extend or replace shadcn defaults — when a cyber component fully replaces a shadcn one (e.g. `CyberButton` replaces `Button`), keep both files; cyber components import shadcn ones only for accessibility primitives (Radix wrappers).

### 6.5 Design system implementation notes

Implement per the cyberpunk design system already provided to the project (Sections 1-10 of that doc). Key callouts:

- Add fonts: Orbitron (headings), JetBrains Mono (body), Share Tech Mono (labels) via `next/font/google` in root layout.
- `.cyber-chamfer` and `.cyber-chamfer-sm` utility classes in `globals.css` using clip-path polygons.
- Scanlines + grid implemented as CSS pseudo-elements on body, not images.
- Keyframes (`blink`, `glitch`, `rgbShift`, `scanline`) in `globals.css`.
- Respect `prefers-reduced-motion`: disable glitch keyframes, keep static text-shadow.

---

## 7. Environment & Config

### 7.1 Env vars (extend existing `.env`)

```
# existing
DATABASE_URL=postgresql+psycopg://jobsearch:jobsearch@localhost:5433/jobsearch
ANTHROPIC_API_KEY=...

# new for this feature
APP_PASSWORD=<set to anything; required>
APP_SECRET=<hex string, 64 chars; required in prod, auto-generated in dev>
RESUME_TEMPLATE_PATH=resume_template.tex   # optional; defaults to repo root
RESUME_MODEL=claude-sonnet-4-6             # optional; defaults to this
```

### 7.2 Web `.env.local`

```
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

That's it. Everything else proxies through the API.

---

## 8. Acceptance Criteria

Definition of done for v1:

1. **Auth works:** `/login` accepts the env password; bad password shows error; cookie persists across reloads; logout clears it.
2. **Applications list:** `/applications` shows non-`discovered` rows from `scored_results`, filterable by status; clicking a row navigates to detail.
3. **Status transitions:** detail page can change status; invalid transitions return 422 and UI shows the error inline.
4. **Notes auto-save:** typing in notes debounces 800ms then PATCHes; refresh shows saved value.
5. **Resume generation:** "Generate tailored resume" button on detail page calls API, returns valid LaTeX (starts with `\documentclass`, ends with `\end{document}`), shows in browser, downloads as `.tex`.
6. **Resume history:** all past versions appear in the detail page, newest first; clicking shows that version's `tex_content`.
7. **Prompt-hash dedup:** clicking generate twice in a row without changes shows "existing version" modal.
8. **Dashboard:** `/` shows status counts that match DB. Numbers update on next refresh after a transition.
9. **Cyberpunk styling:** scanlines visible, headings glow, buttons chamfered, hover effects working, all custom fonts loaded.
10. **No regressions:** `python main.py --daemon` still runs and writes to DB; daemon doesn't crash on the new columns.

### 8.1 Verification

- Run migration: `docker exec job-search-postgres psql -U jobsearch -d jobsearch -f /tmp/2026-05-24_app_tracking.sql`
- Start all three processes per Section 2 process model.
- Manual walkthrough: login → dashboard → jobs → click one → change status → add notes → generate resume → download .tex → open in TeX Live and confirm it compiles cleanly (do this once locally; not part of automated verification).

### 8.2 Out of scope (explicit non-goals)

- Tests: skip automated tests for v1. Manual walkthrough only.
- Mobile responsiveness past "doesn't break at 375px". Cyber design is laptop-first.
- VPS deployment (separate spec).
- Cover letters, contact info enrichment, multi-user, kanban DnD.

---

## 9. VPS Deploy Notes (FUTURE, not v1)

For when this moves to Contabo:

- Build Next: `pnpm build` → `pnpm start` on :3000.
- Systemd units for `api` (`uvicorn`), `web` (`pnpm start`), `daemon` (`python main.py --daemon`).
- Caddy in front: `auto-https`, `basicauth /api/*` as belt-and-suspenders on top of cookie auth, websocket support not needed.
- Postgres bound to 127.0.0.1 only; `pg_hba.conf` rejects non-local.
- Nightly `pg_dump` to `/var/backups/jobsearch_$(date).sql.gz`, retain 14 days.
- `APP_SECRET` and `APP_PASSWORD` set via systemd `EnvironmentFile=` pointing at a `0600`-mode file.

---

## 10. Implementation Order (for Codex)

1. **Migration + models** (~30 min) — write SQL file, ALTER + CREATE on local DB, update [db/models.py](db/models.py), confirm daemon still runs.
2. **FastAPI skeleton + auth** (~1 hr) — `api/main.py`, `api/auth.py`, `/api/auth/*`, `/api/me`. Manually curl-test login.
3. **Application routes** (~1 hr) — `/api/applications/*` GET/PATCH, with state-machine validation. Manually curl-test.
4. **Resume route + Claude call** (~1.5 hr) — `/api/applications/{id}/resumes` POST + GET, prompt hashing, version storage. Manually verify Claude returns valid LaTeX.
5. **Next.js scaffold** (~30 min) — `create-next-app` in `web/`, install shadcn primitives, set up Tailwind tokens from cyberpunk design system.
6. **Cyber components** (~2 hr) — `components/cyber/*` per Section 6.3, with all CSS keyframes + utility classes in `globals.css`.
7. **Pages** (~3 hr) — login → dashboard → jobs → applications → application detail, in that order. Auth middleware. Wire to API via `lib/api.ts`.
8. **Polish** (~1 hr) — toast feedback, loading skeletons, error states, focus rings, reduced-motion check.

Total estimate: ~10 hours of focused work. Ship in 2 sittings.
