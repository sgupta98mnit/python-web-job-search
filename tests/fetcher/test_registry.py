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
