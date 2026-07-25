"""In-process token-bucket rate limiter for plugin authors respecting an external API's own
rate limits. See docs/plugins/PLUGIN_ARCHITECTURE.md §"Rate limiting & backoff".

Deliberately dependency-free and process-local (no Redis, no external service) to keep the
plugin SDK free of a dependency on any particular backing store — see plugins/_shared/base.py's
module docstring on why plugins/_shared stays free of heavyweight dependencies. This is
sufficient for GrowthOS's current single-worker-process deployment
(docs/deployment/DEPLOYMENT.md); it is a known, deliberate limitation, not an oversight — see
`RateLimiter`'s docstring.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class RateLimiter:
    """One token bucket per `(plugin_key, project_id)` pair. `capacity` tokens refill at
    `refill_rate` tokens/second. Call `try_acquire()` before making an external API call; if
    it returns `False`, skip the call and return fewer/no results plus a logged warning — do
    not raise. This is the documented contract: "a throttled plugin returns fewer/no results
    and logs a warning rather than raising, so one rate-limited plugin never fails an entire
    agent run" (docs/plugins/PLUGIN_ARCHITECTURE.md).

    **Known limitation — process-local only.** Each worker process/replica gets its own
    buckets. This is correct for a single-process deployment; under multiple replicas of the
    same worker, each replica enforces the limit independently, so the *effective* aggregate
    rate against the external API becomes `replica_count × capacity`, not one globally shared
    ceiling. Acceptable at GrowthOS's current scale; if/when multiple replicas of the same
    worker become real, this would need a shared (most likely Redis) backend behind the same
    two-method interface — a swap, not a redesign, since callers only ever see
    `try_acquire()`.
    """

    def __init__(self, *, capacity: int, refill_rate: float) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate <= 0:
            raise ValueError("refill_rate must be positive")
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    def try_acquire(self, *, plugin_key: str, project_id: str, cost: int = 1) -> bool:
        """Returns True and deducts `cost` tokens if enough were available, False (and
        deducts nothing) otherwise."""
        key = (plugin_key, project_id)
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
