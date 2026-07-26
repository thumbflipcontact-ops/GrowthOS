"""Unit tests for app/core/observability.py — see docs/reviews/PRODUCTION_READINESS_REVIEW.md
O8/O9 and docs/reviews/PRODUCTION_HARDENING_REPORT.md.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import app.core.observability as observability
from app.core.config import Settings


def _settings(*, sentry_dsn: str | None = None) -> Settings:
    return Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
        sentry_dsn=sentry_dsn,
    )


@pytest.fixture(autouse=True)
def _reset_enabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    # _enabled is a module-level singleton (one real process = one Sentry client) — force a
    # known starting state for every test rather than leaking state across the test session.
    monkeypatch.setattr(observability, "_enabled", False)


def test_init_is_a_noop_without_a_dsn() -> None:
    observability.init_error_tracking(_settings(sentry_dsn=None), process_name="test")
    assert observability._enabled is False


def test_init_enables_tracking_when_a_dsn_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sentry_sdk = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", fake_sentry_sdk)

    observability.init_error_tracking(
        _settings(sentry_dsn="https://example.invalid/1"), process_name="test-worker"
    )

    assert observability._enabled is True
    fake_sentry_sdk.init.assert_called_once()
    _, kwargs = fake_sentry_sdk.init.call_args
    assert kwargs["dsn"] == "https://example.invalid/1"
    assert kwargs["server_name"] == "test-worker"


def test_capture_exception_is_a_noop_when_not_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sentry_sdk = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", fake_sentry_sdk)

    observability.capture_exception(RuntimeError("boom"))

    fake_sentry_sdk.capture_exception.assert_not_called()


def test_capture_exception_forwards_to_sentry_once_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sentry_sdk = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", fake_sentry_sdk)
    observability.init_error_tracking(
        _settings(sentry_dsn="https://example.invalid/1"), process_name="test"
    )

    exc = RuntimeError("boom")
    observability.capture_exception(exc)

    fake_sentry_sdk.capture_exception.assert_called_once_with(exc)
