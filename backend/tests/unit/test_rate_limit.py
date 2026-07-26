"""Unit tests for app/core/rate_limit.py — see docs/reviews/PRODUCTION_READINESS_REVIEW.md
S1 and docs/reviews/PRODUCTION_HARDENING_REPORT.md.
"""

from __future__ import annotations

import pytest

from app.core.rate_limit import RateLimiter


def test_allows_up_to_capacity_then_denies() -> None:
    limiter = RateLimiter(capacity=3, refill_rate=0.001)  # negligible refill within the test
    assert limiter.try_acquire("k") is True
    assert limiter.try_acquire("k") is True
    assert limiter.try_acquire("k") is True
    assert limiter.try_acquire("k") is False


def test_different_keys_have_independent_buckets() -> None:
    limiter = RateLimiter(capacity=1, refill_rate=0.001)
    assert limiter.try_acquire("a") is True
    assert limiter.try_acquire("a") is False
    assert limiter.try_acquire("b") is True  # unaffected by "a"'s exhaustion


def test_refill_over_time_restores_tokens() -> None:
    # Manipulates the bucket's internal last_refill directly rather than a real time.sleep()
    # — deterministic and instant, not dependent on the host's scheduler/timer resolution
    # actually honoring a short real sleep (observed flaky under load with a real sleep).
    limiter = RateLimiter(capacity=1, refill_rate=1000.0)  # effectively instant refill
    assert limiter.try_acquire("k") is True
    assert limiter.try_acquire("k") is False

    bucket = limiter._buckets["k"]
    bucket.last_refill -= 1.0  # simulate 1 real second elapsed — 1000 tokens, capped at 1

    assert limiter.try_acquire("k") is True


def test_capacity_and_refill_rate_must_be_positive() -> None:
    with pytest.raises(ValueError):
        RateLimiter(capacity=0, refill_rate=1.0)
    with pytest.raises(ValueError):
        RateLimiter(capacity=1, refill_rate=0.0)
