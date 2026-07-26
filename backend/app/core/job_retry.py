"""Shared retry-backoff helper for Arq job bodies.

See docs/reviews/PRODUCTION_READINESS_REVIEW.md §3.1 and
docs/reviews/PRODUCTION_HARDENING_REPORT.md. Every job in this codebase used to re-raise a
plain exception on a transient failure, intending Arq's `WorkerSettings.max_tries` to retry
it — but Arq only retries a job that raises `arq.worker.Retry` specifically; a plain exception
(or any other exception subclass) is treated as a permanent failure after exactly one
attempt, regardless of `max_tries`. This module is the one place the correct exception type
and a shared exponential-backoff formula live, so every job re-raises the same way.
"""

from __future__ import annotations

MAX_BACKOFF_SECONDS = 60


def retry_backoff_seconds(job_try: int) -> int:
    """Exponential backoff, capped, keyed off Arq's own `ctx["job_try"]` (1 on the first
    attempt). 2s, 4s, 8s, 16s, ... up to MAX_BACKOFF_SECONDS."""
    return min(int(2 ** min(job_try, 30)), MAX_BACKOFF_SECONDS)
