"""Resume tailoring through Claude."""

from __future__ import annotations

import hashlib
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from anthropic import Anthropic

import config
from db.models import ScoredResult, SearchResult

RESUME_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a resume tailoring assistant. You will be given:
1. A complete LaTeX resume template (the candidate's base resume).
2. A target job posting (title, snippet, URL).
3. The candidate's profile/criteria.

Your job: return a tailored copy of the LaTeX resume that emphasizes the candidate's
fit for this specific job, by:
- Rewriting the Professional Summary paragraph to lead with the most-relevant keywords.
- Rewriting Experience bullets to emphasize tasks/skills the JD asks for. You may reorder
  bullets within a role. You may NOT add fictional experience. You MAY rephrase real bullets.
- Reordering the Skills buckets so most-relevant comes first. You MAY add or remove
  \\textbf{} emphasis on specific skill items to align with JD keywords.

You MUST preserve verbatim:
- Every LaTeX command, package import, and preamble line.
- All custom commands (\\resumeSubheading, \\resumeItemA, \\resumeSubItemWithLink, etc.).
- The Education section in full.
- Company names, job titles, and date ranges in Experience headings.
- The Projects section in full.
- The document's overall section order.

Output ONLY the complete tailored .tex file content, starting with \\documentclass and
ending with \\end{document}. No prose, no markdown, no code fences, no commentary."""


def load_template() -> str:
    path = Path(os.getenv("RESUME_TEMPLATE_PATH", "resume_template.tex"))
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return path.read_text(encoding="utf-8")


def resume_model() -> str:
    return os.getenv("RESUME_MODEL", RESUME_MODEL)


def build_user_message(
    template: str,
    scored: ScoredResult,
    search: SearchResult,
    criteria: str | None = None,
) -> str:
    criteria_text = criteria if criteria is not None else config.CRITERIA
    title = scored.title or search.title
    return f"""<resume_template>
{template}
</resume_template>

<job_posting>
Title: {title}
Company: {scored.company}
Location: {scored.location}
URL: {search.url}
Snippet:
{search.snippet}
</job_posting>

<candidate_profile>
{criteria_text}
</candidate_profile>"""


def prompt_hash(
    template: str,
    scored: ScoredResult,
    search: SearchResult,
    criteria: str | None = None,
) -> str:
    criteria_text = criteria if criteria is not None else config.CRITERIA
    title = scored.title or search.title
    raw = template + title + search.snippet + criteria_text
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_tailored_resume(user_message: str, model: str) -> tuple[str, dict[str, Any], int]:
    client = Anthropic()
    t0 = time.monotonic()
    response = client.messages.create(
        model=model,
        max_tokens=12000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    raw = response.model_dump(mode="json")
    return _clean_tex(_response_text(response.content)), raw, latency_ms


def looks_like_tex(content: str) -> bool:
    stripped = content.strip()
    return stripped.startswith("\\documentclass") and stripped.endswith("\\end{document}")


def slugify(value: str, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return (slug[:30].strip("-") or fallback)


def _response_text(content: list[Any]) -> str:
    return "\n".join(block.text for block in content if getattr(block, "type", None) == "text")


def _clean_tex(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:tex|latex)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped
