"""LLM-provider error hierarchy — see docs/decisions/0004-llm-provider-abstraction.md.

Kept separate from app/core/errors.py's HTTP-mapped domain exceptions, the same pattern
app/core/oauth/errors.py already uses: these are provider-level errors raised by
app/core/llm/*_provider.py, translated into the app-wide domain exceptions at whatever
boundary calls them (an agent's run(), a job body) if a caller needs an HTTP-mapped response
— no such boundary exists yet for LLM calls, since nothing in the API surface calls one
directly (only agent job bodies do).
"""

from __future__ import annotations


class LLMError(Exception):
    """Base for all LLM-provider errors."""


class LLMRequestFailed(LLMError):
    """The provider's API could not be reached, or returned an error response (rate limit,
    auth failure, server error, ...). Callers should generally let this propagate — an
    agent's run() calling `ctx.llm.complete(...)` is exactly the kind of transient failure
    Arq's job-retry policy (docs/jobs/BACKGROUND_JOBS.md) exists for, the same way a plugin's
    network failure does."""


class LLMProviderNotConfigured(LLMError):
    """The operator hasn't set the API key this provider needs (see
    app/core/config.py's Settings), or requested a provider with no implementation yet
    (e.g. `LLM_PRIMARY_PROVIDER=openai` — see app/core/llm/factory.py). Raised at first use,
    not at process startup — mirrors OAuthClientNotConfigured's timing rationale."""


__all__ = ["LLMError", "LLMProviderNotConfigured", "LLMRequestFailed"]
