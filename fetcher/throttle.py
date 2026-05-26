"""Per-host rate limiter. One lock + last-acquire timestamp per host.

Used by fetcher.client to space outbound HTTP GETs to the same host even
when the threadpool would otherwise issue them concurrently. A different
host never blocks on this lock.
"""

from __future__ import annotations

import threading
import time


class HostTokenBucket:
    """rps requests per second per host. Capacity is effectively 1
    (single-token bucket); we just delay until `1/rps` has elapsed since
    the previous acquire for the same host."""

    def __init__(self, rps: float) -> None:
        if rps <= 0:
            raise ValueError("rps must be > 0")
        self._period = 1.0 / rps
        self._lock = threading.Lock()
        self._next_allowed: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}

    def _lock_for(self, host: str) -> threading.Lock:
        with self._lock:
            lk = self._host_locks.get(host)
            if lk is None:
                lk = threading.Lock()
                self._host_locks[host] = lk
            return lk

    def acquire(self, host: str) -> None:
        """Block until a request to `host` is allowed; then mark the
        next-allowed timestamp."""
        host_lock = self._lock_for(host)
        with host_lock:
            now = time.monotonic()
            next_allowed = self._next_allowed.get(host, 0.0)
            if now < next_allowed:
                time.sleep(next_allowed - now)
                now = time.monotonic()
            self._next_allowed[host] = now + self._period
