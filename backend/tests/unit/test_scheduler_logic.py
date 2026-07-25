"""Pure logic test for the cron due-check — see docs/jobs/BACKGROUND_JOBS.md."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.scheduler import is_due


def test_every_minute_cron_is_due_after_a_minute_window() -> None:
    now = datetime(2026, 7, 25, 10, 0, 0, tzinfo=UTC)
    since = now - timedelta(minutes=1)
    assert is_due("* * * * *", since, now) is True


def test_daily_cron_is_not_due_within_an_unrelated_minute_window() -> None:
    now = datetime(2026, 7, 25, 10, 30, 0, tzinfo=UTC)
    since = now - timedelta(minutes=1)
    assert is_due("0 0 * * *", since, now) is False


def test_daily_cron_is_due_when_window_crosses_midnight() -> None:
    now = datetime(2026, 7, 26, 0, 0, 30, tzinfo=UTC)
    since = now - timedelta(minutes=1)
    assert is_due("0 0 * * *", since, now) is True


def test_empty_window_is_never_due() -> None:
    now = datetime(2026, 7, 25, 10, 0, 0, tzinfo=UTC)
    assert is_due("* * * * *", now, now) is False
