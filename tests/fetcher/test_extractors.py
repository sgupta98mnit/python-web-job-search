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
