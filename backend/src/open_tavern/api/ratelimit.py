"""Minimal in-memory rate limiter for paid-LLM endpoints.

A per-key sliding window with no external dependencies. Kept deliberately small:
the API is a single-process local tool, so an in-memory limiter is sufficient
and avoids pulling in a distributed rate-limit dependency.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    """Sliding-window rate limiter keyed by an arbitrary string."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Return ``True`` and record a hit if ``key`` is under the limit."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        """Clear all recorded hits."""
        with self._lock:
            self._hits.clear()
