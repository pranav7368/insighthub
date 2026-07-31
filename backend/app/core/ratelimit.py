"""In-process sliding-window rate limiter.

Keyed by client IP + a route category (auth / llm / public / default), it caps
requests per window to blunt brute-force and abuse. This is per-process state —
good for a single node; a multi-worker deployment should front it with a shared
store (Redis) or a gateway limiter. Disabled automatically under tests.
"""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._clock = clock

    def check(self, key: str, limit: int, window: float) -> tuple[bool, float]:
        """Record a hit for `key`. Returns (allowed, retry_after_seconds)."""
        now = self._clock()
        dq = self._hits[key]
        cutoff = now - window
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False, max(0.0, window - (now - dq[0]))
        dq.append(now)
        return True, 0.0

    def reset(self) -> None:
        self._hits.clear()


# Process-wide limiter used by the API middleware.
limiter = RateLimiter()


def bucket_for(path: str, cfg) -> tuple[str, int]:
    """Map a request path to a (category, limit) using the config module."""
    if path.startswith("/api/auth/"):
        return "auth", cfg.RATELIMIT_AUTH
    if path == "/api/ask" or path.endswith("/query") or path.endswith("/narrative"):
        return "llm", cfg.RATELIMIT_LLM
    if path.startswith("/api/public/"):
        return "public", cfg.RATELIMIT_PUBLIC
    return "default", cfg.RATELIMIT_DEFAULT
