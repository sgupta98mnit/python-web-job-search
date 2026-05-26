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
