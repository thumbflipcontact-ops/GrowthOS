from __future__ import annotations

import time

import pytest

from plugins._shared.rate_limit import RateLimiter


def test_allows_up_to_capacity_then_blocks() -> None:
    limiter = RateLimiter(capacity=3, refill_rate=0.001)
    assert limiter.try_acquire(plugin_key="p", project_id="proj") is True
    assert limiter.try_acquire(plugin_key="p", project_id="proj") is True
    assert limiter.try_acquire(plugin_key="p", project_id="proj") is True
    assert limiter.try_acquire(plugin_key="p", project_id="proj") is False


def test_buckets_are_isolated_per_plugin_and_project() -> None:
    limiter = RateLimiter(capacity=1, refill_rate=0.001)
    assert limiter.try_acquire(plugin_key="reddit", project_id="proj-a") is True
    # Different project, same plugin — its own bucket, unaffected by proj-a's usage.
    assert limiter.try_acquire(plugin_key="reddit", project_id="proj-b") is True
    # Different plugin, same project — likewise its own bucket.
    assert limiter.try_acquire(plugin_key="linkedin", project_id="proj-a") is True
    # proj-a/reddit's single token is already spent.
    assert limiter.try_acquire(plugin_key="reddit", project_id="proj-a") is False


def test_tokens_refill_over_time() -> None:
    # A large refill_rate + a comparatively long sleep gives generous margin against
    # Windows' ~15ms timer granularity and general scheduling jitter — this only needs ONE
    # token to have refilled, and at this rate that happens within microseconds of the sleep
    # starting, not right at its edge.
    limiter = RateLimiter(capacity=1, refill_rate=10_000.0)
    assert limiter.try_acquire(plugin_key="p", project_id="proj") is True
    assert limiter.try_acquire(plugin_key="p", project_id="proj") is False
    time.sleep(0.05)
    assert limiter.try_acquire(plugin_key="p", project_id="proj") is True


def test_refill_never_exceeds_capacity() -> None:
    limiter = RateLimiter(capacity=2, refill_rate=10_000.0)
    time.sleep(0.1)  # plenty of time to over-refill if capacity weren't capped
    assert limiter.try_acquire(plugin_key="p", project_id="proj", cost=2) is True
    assert limiter.try_acquire(plugin_key="p", project_id="proj") is False


def test_rejects_non_positive_capacity_or_refill_rate() -> None:
    with pytest.raises(ValueError):
        RateLimiter(capacity=0, refill_rate=1.0)
    with pytest.raises(ValueError):
        RateLimiter(capacity=1, refill_rate=0.0)
