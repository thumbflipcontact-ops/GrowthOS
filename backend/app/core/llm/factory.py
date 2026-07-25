"""Resolves `Settings.llm_primary_provider` into a real `LLMProvider` instance. See
docs/decisions/0004-llm-provider-abstraction.md.

The one place that knows Claude is the primary provider and OpenAI is (for now) unimplemented
— agent code and job bodies call `build_llm_provider(settings)`, never construct a provider
directly.
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.llm.anthropic_provider import AnthropicProvider
from app.core.llm.base import LLMProvider
from app.core.llm.errors import LLMProviderNotConfigured


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_primary_provider == "anthropic":
        return AnthropicProvider(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.anthropic_model,
        )

    # "openai" is a valid Settings value (ADR 0004 names it the secondary provider) but has
    # no implementation yet — see backend/README.md's "explicitly not present" list. Raised
    # here, at first use, rather than rejected at the Settings-validation layer, since the
    # value itself is legitimate; it just isn't buildable yet.
    raise LLMProviderNotConfigured(
        f"No LLMProvider implementation exists yet for {settings.llm_primary_provider!r}."
    )
