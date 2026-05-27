"""Email digests for newly discovered high-scoring jobs.

Delivery goes through Resend's HTTP API (https://resend.com). Switched from
SMTP after Microsoft disabled basic-auth SMTP on personal Outlook accounts
in late 2024.
"""

from __future__ import annotations

import html
import logging

import requests
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

import config
from db.models import EmailNotification, ScoredResult, SearchResult

log = logging.getLogger(__name__)

PendingJob = tuple[ScoredResult, SearchResult]


def notify_unsent_jobs(session: Session) -> int:
    """Send one digest for all unsent jobs above the configured threshold."""
    if not config.EMAIL_NOTIFICATIONS_ENABLED:
        print("Email notifications disabled.")
        return 0

    recipient = config.EMAIL_TO.strip()
    if not recipient:
        print("Email notifications skipped: EMAIL_TO is empty.")
        return 0

    pending = _pending_jobs(
        session,
        recipient=recipient,
        threshold=config.EMAIL_SCORE_THRESHOLD,
    )
    if not pending:
        print(
            "Email notifications: no unsent jobs "
            f"with score > {config.EMAIL_SCORE_THRESHOLD}."
        )
        return 0

    if not _resend_configured():
        print(
            "Email notifications skipped: set RESEND_API_KEY in .env. "
            "Get a key at https://resend.com (free tier sends from "
            "onboarding@resend.dev to the account owner's address)."
        )
        return 0

    subject = (
        f"Job search: {len(pending)} new "
        f"job{'s' if len(pending) != 1 else ''} above "
        f"{config.EMAIL_SCORE_THRESHOLD}"
    )
    _send_via_resend(
        recipient=recipient,
        subject=subject,
        text_body=_plain_body(pending),
        html_body=_html_body(pending),
    )

    for scored, search in pending:
        session.add(
            EmailNotification(
                scored_result_id=scored.id,
                recipient=recipient,
                normalized_url=search.normalized_url,
                subject=subject,
            )
        )
    session.flush()
    print(f"Email notifications: sent {len(pending)} jobs to {recipient}.")
    return len(pending)


def _pending_jobs(
    session: Session,
    *,
    recipient: str,
    threshold: int,
) -> list[PendingJob]:
    stmt = (
        select(ScoredResult, SearchResult)
        .join(SearchResult, ScoredResult.search_result_id == SearchResult.id)
        .outerjoin(
            EmailNotification,
            and_(
                EmailNotification.recipient == recipient,
                EmailNotification.normalized_url == SearchResult.normalized_url,
            ),
        )
        .where(ScoredResult.is_job.is_(True))
        .where(ScoredResult.score > threshold)
        .where(EmailNotification.id.is_(None))
        .order_by(
            ScoredResult.score.desc(),
            ScoredResult.created_at.desc(),
            ScoredResult.id.desc(),
        )
    )

    jobs: list[PendingJob] = []
    seen_urls: set[str] = set()
    for scored, search in session.execute(stmt):
        if search.normalized_url in seen_urls:
            continue
        seen_urls.add(search.normalized_url)
        jobs.append((scored, search))
    return jobs


def _resend_configured() -> bool:
    return bool(config.RESEND_API_KEY.strip() and config.EMAIL_FROM.strip())


def _plain_body(jobs: list[PendingJob]) -> str:
    lines = [
        f"Unsent jobs with score > {config.EMAIL_SCORE_THRESHOLD}: {len(jobs)}",
        "",
    ]
    for idx, (scored, search) in enumerate(jobs, start=1):
        location = scored.location or "unknown location"
        if scored.remote:
            location = f"{location} (remote)"
        lines.extend(
            [
                f"{idx}. [{scored.score}] {scored.title or search.title}",
                f"   Company: {scored.company or 'unknown'}",
                f"   Location: {location}",
                f"   URL: {search.url}",
            ]
        )
        if scored.reason:
            lines.append(f"   Reason: {scored.reason}")
        lines.append("")
    return "\n".join(lines)


def _html_body(jobs: list[PendingJob]) -> str:
    rows = []
    for scored, search in jobs:
        title = html.escape(scored.title or search.title or "Untitled job")
        company = html.escape(scored.company or "unknown")
        location = scored.location or "unknown location"
        if scored.remote:
            location = f"{location} (remote)"
        reason = html.escape(scored.reason or "")
        url = html.escape(search.url, quote=True)
        rows.append(
            "<tr>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{scored.score}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'><a href='{url}'>{title}</a></td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{company}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{html.escape(location)}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{reason}</td>"
            "</tr>"
        )

    return (
        "<html><body>"
        f"<p>Unsent jobs with score &gt; {config.EMAIL_SCORE_THRESHOLD}: {len(jobs)}</p>"
        "<table style='border-collapse:collapse;width:100%;'>"
        "<thead><tr>"
        "<th align='left'>Score</th><th align='left'>Job</th>"
        "<th align='left'>Company</th><th align='left'>Location</th>"
        "<th align='left'>Reason</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</body></html>"
    )


def _send_via_resend(
    *,
    recipient: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    """POST to Resend's /emails endpoint. Raises on non-2xx."""
    payload = {
        "from": config.EMAIL_FROM.strip(),
        "to": [recipient],
        "subject": subject,
        "text": text_body,
        "html": html_body,
    }
    resp = requests.post(
        config.RESEND_API_URL,
        json=payload,
        headers={"Authorization": f"Bearer {config.RESEND_API_KEY.strip()}"},
        timeout=config.RESEND_TIMEOUT,
    )
    if resp.status_code >= 400:
        # Resend returns {"name": "...", "message": "..."} on error.
        try:
            err = resp.json()
            detail = err.get("message") or err.get("name") or resp.text
        except ValueError:
            detail = resp.text
        raise RuntimeError(
            f"Resend send failed ({resp.status_code}): {detail}"
        )
