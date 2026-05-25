# Codex Handoff Prompt

Copy the block below verbatim into Codex (or any coding agent). It is self-contained —
no prior conversation context required.

---

## PROMPT START

You are implementing two features in an existing Python codebase: **application tracking** and a **per-job tailored resume builder**, with a Next.js cyberpunk-styled UI on top.

**Full design spec:** `docs/superpowers/specs/2026-05-24-app-tracking-resume-builder-design.md`
**Cyberpunk design system:** the user has provided a complete design system document; honor every token, animation, and component pattern in it. Key signatures: chamfered corners (clip-path), neon glow box-shadows, scanline overlays, chromatic-aberration glitch effects, monospace typography (Orbitron headings, JetBrains Mono body), pure-dark `#0a0a0f` background, primary accent `#00ff88`.

**Read the spec in full before writing any code.** Implement Sections 2 through 8 in the order given in Section 10 (Implementation Order).

### Existing codebase context

- Python 3.12 project with SQLAlchemy 2.x, Postgres in docker on port 5433.
- Daemon at `main.py` runs continuously, writing search results and Claude-scored results to Postgres. **Do not modify the daemon or anything in `search.py`, `score.py`, `providers/`, `searchers/`.** Only `db/models.py` may be extended.
- Existing schema is created by `Base.metadata.create_all()` in `db/bootstrap.py`. There is no Alembic. New columns/tables are added via one-shot SQL files in `db/migrations_sql/` applied manually with `docker exec`.
- Anthropic API key is in `.env` as `ANTHROPIC_API_KEY`.
- Postgres connection string is in `.env` as `DATABASE_URL`.

### Scope

This work introduces:
- 4 new columns on `scored_results` + 1 new table `resume_versions` (Section 3).
- A new `api/` FastAPI app with ~12 endpoints (Section 4).
- A new `web/` Next.js 15 App Router app with 5 pages and ~10 components (Section 6).
- Auth via single-password env var + signed cookie (Section 4.2).
- LaTeX resume tailoring via direct Anthropic SDK call to claude-sonnet-4-6 (Section 5).
- New env vars: `APP_PASSWORD`, `APP_SECRET`, optional `RESUME_TEMPLATE_PATH`, optional `RESUME_MODEL`.

The user's `resume_template.tex` is already at the repo root.

### Constraints and conventions

- **Match existing Python style:** type hints throughout, `from __future__ import annotations`, no docstrings beyond one-liners where intent is non-obvious, no defensive try/except around things that can't fail in practice. Look at `search.py` and `score.py` for the conventions.
- **Match the design system's TypeScript style on the Next side:** strict TS, no `any`, server components by default, `"use client"` only when needed (forms, interactivity).
- **Single Postgres, single transaction per request.** Use FastAPI dependency injection (`Depends(get_session)`) for DB sessions, not module-level globals.
- **No tests for v1.** Manual walkthrough per Section 8.1 of the spec.
- **No backwards-compatibility shims.** This is a clean addition; don't add feature flags.
- **Do not run the daemon while developing.** Stop it first.
- **Cyberpunk styling is not optional.** Apply it consistently across every page from the start, not as a polish pass at the end. shadcn primitives must be restyled to cyber tokens via `tailwind.config.ts` before any page work begins.

### Verification

After each section in the Implementation Order:

1. **Migration + models:** run the SQL file via docker exec, verify column existence with `\d scored_results`. Start the daemon briefly with `python main.py` (one cycle, then Ctrl-C) — it must not error.
2. **FastAPI auth:** `curl -X POST http://localhost:8000/api/auth/login -d '{"password":"..."}' -H 'Content-Type: application/json'`. Verify Set-Cookie header. Then `curl http://localhost:8000/api/me --cookie-jar /tmp/c -b /tmp/c` returns `{"ok": true}`.
3. **Applications routes:** GET `/api/applications` returns array. PATCH with invalid status transition returns 422.
4. **Resume route:** POST returns a `ResumeVersion` whose `tex_content` starts with `\documentclass` and ends with `\end{document}`. Second POST with no changes returns the same row id.
5. **Next.js:** `pnpm dev` runs without TypeScript errors. `/login` redirects to `/` on valid password. Middleware blocks `/` when no cookie present.
6. **Cyber components:** visually inspect — chamfered corners visible, headings glow, hover effects working, scanlines overlaid on entire page.
7. **End-to-end:** complete the walkthrough in spec Section 8.1.

Report back at each checkpoint with what was verified.

### What to ask the user about

The spec is opinionated and complete. Implement it as specified. Only ask if you encounter:

- A library version conflict that requires switching to a different package.
- An ambiguity in the spec where two equally-valid interpretations exist (cite the section).
- A platform-specific issue (Windows PowerShell vs Bash for the dev workflow).

Otherwise, make the implementation choice and document it inline.

### Start by

1. Reading `docs/superpowers/specs/2026-05-24-app-tracking-resume-builder-design.md` end to end.
2. Reading `db/models.py`, `db/bootstrap.py`, `config.py`, `main.py` to internalize the existing patterns.
3. Reading the cyberpunk design system the user already provided (it's in the project context).
4. Beginning with Section 10 step 1: write the SQL migration, run it, extend the models.

## PROMPT END

---

## Notes for the user

- The prompt above assumes Codex has access to the repo and can run shell commands.
- If Codex pushes back on the no-tests rule, that's fine — let it add tests; the spec just doesn't require them.
- If Codex gets stuck on the cyberpunk styling, point it at the design system doc explicitly — that's the most likely thing it'll under-deliver on without nudging.
- Implementation estimate: ~10 hours of focused agent work. Expect 2-3 sittings with checkpoints.
- After v1 ships and feels right, the natural next features (per spec Section 8.2): mobile responsive pass, cover letter drafter, VPS deploy.
