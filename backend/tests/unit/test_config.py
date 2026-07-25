"""See docs/config/CONFIGURATION.md."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _base_env() -> dict:
    return {
        "database_url": "postgresql://u:p@localhost:5432/growthos",
        "redis_url": "redis://localhost:6379/0",
        "anthropic_api_key": "x",
        "openai_api_key": "x",
        "secret_key": "x",
        "credential_master_key": "x",
    }


def test_settings_loads_with_required_fields() -> None:
    settings = Settings(**_base_env())
    assert settings.environment == "local"
    assert settings.llm_primary_provider == "anthropic"
    assert settings.is_local is True


def test_settings_rejects_missing_required_field(monkeypatch: pytest.MonkeyPatch) -> None:
    # BaseSettings falls back to the process environment for any field not passed
    # explicitly — conftest.py sets SECRET_KEY there for every other test's benefit, so it
    # must be removed for the duration of this one, or the fallback would mask the missing
    # field this test exists to catch.
    monkeypatch.delenv("SECRET_KEY", raising=False)
    env = _base_env()
    del env["secret_key"]
    with pytest.raises(ValidationError):
        Settings(**env)


def test_settings_rejects_invalid_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_env(), environment="production-typo")


def test_secrets_are_not_plain_strings() -> None:
    settings = Settings(**_base_env())
    # SecretStr must never render its value via str()/repr() — see
    # docs/logging/LOGGING.md "What never gets logged".
    assert "x" not in str(settings.secret_key)
    assert settings.secret_key.get_secret_value() == "x"
