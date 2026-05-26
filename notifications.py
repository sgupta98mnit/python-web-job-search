"""Email digests for newly discovered high-scoring jobs."""

from __future__ import annotations

import html
import smtplib
from email.message import EmailMessage

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

import config
from db.models import EmailNotification, ScoredResult, SearchResult

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

    if not _smtp_configured():
        print(
            "Email notifications skipped: set SMTP_USERNAME and SMTP_PASSWORD "
            "in .env to send through Outlook SMTP."
        )
        return 0

    subject = (
        f"Job search: {len(pending)} new "
        f"job{'s' if len(pending) != 1 else ''} above "
        f"{config.EMAIL_SCORE_THRESHOLD}"
    )
    msg = _build_message(pending, recipient=recipient, subject=subject)
    _send_message(msg)

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


def _smtp_configured() -> bool:
    return bool(
        config.SMTP_HOST.strip()
        and config.SMTP_USERNAME.strip()
        and config.SMTP_PASSWORD.strip()
    )


def _build_message(
    jobs: list[PendingJob],
    *,
    recipient: str,
    subject: str,
) -> EmailMessage:
    sender = config.SMTP_FROM.strip() or config.SMTP_USERNAME.strip()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(_plain_body(jobs))
    msg.add_alternative(_html_body(jobs), subtype="html")
    return msg


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


def _send_message(msg: EmailMessage) -> None:
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
        if config.SMTP_STARTTLS:
            smtp.starttls()
        smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        smtp.send_message(msg)
