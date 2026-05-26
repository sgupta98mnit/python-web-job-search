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
