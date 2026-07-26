"""Generic in-process token-bucket rate limiter for backend-owned endpoints — see
docs/reviews/PRODUCTION_READINESS_REVIEW.md S1 and
docs/reviews/PRODUCTION_HARDENING_REPORT.md. First consumer: `POST /auth/login`
(app/api/v1/auth.py).

Deliberately not `plugins/_shared/rate_limit.py` — that module is scoped to plugin authors
respecting an *external* API's rate limit and is keyed specifically by
`(plugin_key, project_id)`; this one is keyed by an arbitrary string so it fits any
backend-owned use. Same algorithm, same known limitation: process-local only, not shared
across multiple backend replicas. Acceptable at GrowthOS's current single-process deployment
scale (docs/deployment/DEPLOYMENT.md); a future multi-replica deployment would need a shared
(Redis) backend behind this same `try_acquire()` interface — a swap, not a redesign, since
callers only ever see `try_acquire()`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class RateLimiter:
    def __init__(self, *, capacity: int, refill_rate: float) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate <= 0:
            raise ValueError("refill_rate must be positive")
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._buckets: dict[str, _Bucket] = {}

    def try_acquire(self, key: str, *, cost: int = 1) -> bool:
        """Returns True and deducts `cost` tokens if enough were available for `key`, False
        (deducting nothing) otherwise."""
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=float(self.capacity), last_refill=now)
            self._buckets[key] = bucket

        elapsed = now - bucket.last_refill
        bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_rate)
        bucket.last_refill = now

        if bucket.tokens < cost:
            return False
        bucket.tokens -= cost
        return True


__all__ = ["RateLimiter"]
