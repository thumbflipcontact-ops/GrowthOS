"""Unit tests for app/core/analytics.py — mirrors tests/unit/test_observability.py's pattern
for the same "no-op unless the env var is set" module.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import app.core.analytics as analytics
from app.core.config import Settings


def _settings(*, posthog_api_key: str | None = None) -> Settings:
    return Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
        posthog_api_key=posthog_api_key,
    )


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # _client is a module-level singleton (one real process = one PostHog client) — force a
    # known starting state for every test rather than leaking state across the test session.
    monkeypatch.setattr(analytics, "_client", None)


def test_init_is_a_noop_without_an_api_key() -> None:
    analytics.init_analytics(_settings(posthog_api_key=None))
    assert analytics._client is None


def test_init_creates_a_client_when_an_api_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_posthog_module = MagicMock()
    fake_client = MagicMock()
    fake_posthog_module.Posthog.return_value = fake_client
    monkeypatch.setitem(__import__("sys").modules, "posthog", fake_posthog_module)

    analytics.init_analytics(_settings(posthog_api_key="phc_test"))

    assert analytics._client is fake_client
    fake_posthog_module.Posthog.assert_called_once_with(
        project_api_key="phc_test", host="https://us.i.posthog.com"
    )


def test_capture_is_a_noop_when_not_initialized() -> None:
    # Should not raise even though there's no client to forward to.
    analytics.capture("org-1", "subscribed")


def test_capture_forwards_to_the_client_once_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    monkeypatch.setattr(analytics, "_client", fake_client)

    analytics.capture("org-1", "subscribed", plan="standard")

    fake_client.capture.assert_called_once_with(
        "subscribed", distinct_id="org-1", properties={"plan": "standard"}
    )
