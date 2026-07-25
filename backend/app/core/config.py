"""Deployment configuration — see docs/config/CONFIGURATION.md.

Loaded once from environment/.env into a typed, validated Settings object. A missing or
malformed required variable fails fast at process startup, not on the first request that
happens to need it.
"""

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.oauth.errors import OAuthClientNotConfigured


class Settings(BaseSettings):
    # --- Database ---
    database_url: PostgresDsn

    # --- Redis (Arq broker, cache, rate limiting, event dispatch) ---
    redis_url: RedisDsn

    # --- LLM providers — see docs/decisions/0004-llm-provider-abstraction.md.
    # Claude (app/core/llm/anthropic_provider.py) is the only implemented provider as of
    # Phase 2B — see docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md. `openai_api_key`/
    # `llm_primary_provider="openai"` remain valid config (ADR 0004 names OpenAI the
    # secondary provider) with no implementation yet — app/core/llm/factory.py raises
    # LLMProviderNotConfigured at first use, not here, since the value itself is legitimate.
    anthropic_api_key: SecretStr
    anthropic_model: str = Field(
        default="claude-sonnet-4-5",
        description="Which Claude model app/core/llm/anthropic_provider.py requests.",
    )
    openai_api_key: SecretStr
    llm_primary_provider: Literal["anthropic", "openai"] = "anthropic"

    # --- App secrets ---
    secret_key: SecretStr  # session signing
    credential_master_key: SecretStr  # envelope-encryption master key — see docs/security/

    # --- Environment ---
    environment: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"

    # --- Frontend (not consumed by the backend itself; kept for .env parity) ---
    next_public_api_base_url: str = Field(default="http://localhost:8000")

    # --- OAuth2 plugin framework — see docs/auth/OAUTH2_ARCHITECTURE.md ---
    # oauth_callback_base_url must be the exact, publicly reachable origin registered as
    # this deployment's redirect_uri with every OAuth-capable plugin's provider — see
    # docs/auth/OAUTH2_ARCHITECTURE.md §3 on why this is one fixed URL, not
    # project-scoped/templated.
    oauth_callback_base_url: str = Field(default="http://localhost:8000")
    oauth_frontend_redirect_url: str = Field(default="http://localhost:3000/settings/plugins")

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_local(self) -> bool:
        return self.environment == "local"

    def oauth_client_credentials(self, plugin_key: str) -> tuple[SecretStr, SecretStr]:
        """Per-plugin OAuth app-registration credentials — `{PLUGIN_KEY}_OAUTH_CLIENT_ID` /
        `_CLIENT_SECRET` read directly from the environment, deliberately NOT fixed
        `Settings` fields: the plugin set is open-ended (100+ over this system's stated
        lifetime, ARCHITECTURE.md §1), so there is no fixed schema to declare them against —
        see docs/auth/OAUTH2_ARCHITECTURE.md §6. Raised at first use (when a connection
        attempt for this specific plugin is actually initiated), not at process startup,
        since which installed plugins need OAuth credentials is only known after catalog
        discovery has run, not at Settings-load time."""
        prefix = plugin_key.upper().replace("-", "_")
        client_id = os.environ.get(f"{prefix}_OAUTH_CLIENT_ID")
        client_secret = os.environ.get(f"{prefix}_OAUTH_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise OAuthClientNotConfigured(
                f"{prefix}_OAUTH_CLIENT_ID and {prefix}_OAUTH_CLIENT_SECRET must both be set "
                f"in the environment to connect plugin {plugin_key!r}."
            )
        return SecretStr(client_id), SecretStr(client_secret)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — Settings() runs env parsing/validation once per process."""
    return Settings()  # type: ignore[call-arg]  # values come from env/.env at runtime
