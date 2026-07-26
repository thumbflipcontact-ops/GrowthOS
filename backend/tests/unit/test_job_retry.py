"""Unit tests for app/core/job_retry.py — see docs/reviews/PRODUCTION_READINESS_REVIEW.md
§3.1 and docs/reviews/PRODUCTION_HARDENING_REPORT.md.
"""

from __future__ import annotations

from app.core.job_retry import MAX_BACKOFF_SECONDS, retry_backoff_seconds


def test_retry_backoff_doubles_each_try() -> None:
    assert retry_backoff_seconds(1) == 2
    assert retry_backoff_seconds(2) == 4
    assert retry_backoff_seconds(3) == 8
    assert retry_backoff_seconds(4) == 16


def test_retry_backoff_is_capped() -> None:
    assert retry_backoff_seconds(10) == MAX_BACKOFF_SECONDS
    assert retry_backoff_seconds(100) == MAX_BACKOFF_SECONDS
