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
    long_body = "Backend Engineer at Acme. " * 30  # > JD_MIN_BODY_CHARS=400
    with patch("fetcher.client.requests.Session.get",
               return_value=_mock_response(200, _ok_html(long_body))):
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

    long_body = "fresh body for engineers. " * 30
    with patch("fetcher.client.requests.Session.get",
               return_value=_mock_response(200, _ok_html(long_body))):
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
