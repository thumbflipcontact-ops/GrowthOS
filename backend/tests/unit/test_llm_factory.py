"""See app/core/llm/factory.py."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.llm.anthropic_provider import AnthropicProvider
from app.core.llm.errors import LLMProviderNotConfigured
from app.core.llm.factory import build_llm_provider


def _settings(*, llm_primary_provider: str = "anthropic") -> Settings:
    return Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="test-anthropic-key",
        anthropic_model="claude-sonnet-4-5",
        openai_api_key="test-openai-key",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
        llm_primary_provider=llm_primary_provider,  # type: ignore[arg-type]
    )


def test_builds_an_anthropic_provider_by_default() -> None:
    provider = build_llm_provider(_settings())
    assert isinstance(provider, AnthropicProvider)


def test_raises_not_configured_for_openai() -> None:
    with pytest.raises(LLMProviderNotConfigured):
        build_llm_provider(_settings(llm_primary_provider="openai"))
