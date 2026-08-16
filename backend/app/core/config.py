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
    # SQLAlchemy async-engine pooling, explicit rather than left at the library default — see
    # docs/reviews/PRODUCTION_READINESS_REVIEW.md SC2 and docs/scalability/SCALABILITY.md's
    # connection-budget note: a separate engine exists per process (the API, the scheduler,
    # and each of the four Arq worker types), so (pool_size + max_overflow) × process_count
    # must stay comfortably under Postgres's max_connections. The defaults below match
    # SQLAlchemy's own prior implicit defaults (5 + 10 = 15/process) — unchanged behavior
    # unless explicitly tuned down before adding more worker replicas.
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

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

    # --- Frontend ---
    next_public_api_base_url: str = Field(default="http://localhost:8000")
    # The frontend's own origin — CORS allowlist (app/main.py). Cookie-based session auth
    # (app/core/security.py) relies on the frontend and backend sharing a registrable domain
    # (subdomains are fine, e.g. app.example.com + api.example.com — SameSite=Lax cookies
    # flow between same-site origins regardless of port/subdomain) so this being wrong is a
    # silent, confusing "login works but every subsequent request looks unauthenticated"
    # failure, not a loud one — see docs/deployment/DEPLOYMENT.md.
    frontend_origin: str = Field(default="http://localhost:3000")

    # --- OAuth2 plugin framework — see docs/auth/OAUTH2_ARCHITECTURE.md ---
    # oauth_callback_base_url must be the exact, publicly reachable origin registered as
    # this deployment's redirect_uri with every OAuth-capable plugin's provider — see
    # docs/auth/OAUTH2_ARCHITECTURE.md §3 on why this is one fixed URL, not
    # project-scoped/templated.
    oauth_callback_base_url: str = Field(default="http://localhost:8000")
    oauth_frontend_redirect_url: str = Field(default="http://localhost:3000/settings/plugins")

    # --- Error tracking — see app/core/observability.py and
    # docs/reviews/PRODUCTION_READINESS_REVIEW.md O8/O9. Optional: every process runs exactly
    # as before if this is unset. Not the full docs/observability/OBSERVABILITY.md stack —
    # a narrower, more urgent "don't fail silently in a background worker" gap.
    sentry_dsn: str | None = Field(default=None)

    # --- Product analytics — see app/core/analytics.py. Optional, same pattern as
    # sentry_dsn above: every process runs exactly as before if posthog_api_key is unset.
    # posthog_host defaults to PostHog's US Cloud ingest endpoint (this deployment's project
    # is on US Cloud, not EU) — override only if the PostHog project ever migrates region.
    posthog_api_key: str | None = Field(default=None)
    posthog_host: str = Field(default="https://us.i.posthog.com")

    # --- Billing (Phase 4) — see docs/billing/BILLING_ARCHITECTURE.md. Polar, not Stripe:
    # Stripe does not currently allow solo-founder/individual accounts in India to onboard;
    # Polar is a merchant-of-record platform with self-serve onboarding regardless of
    # business-registration status. Unlike per-plugin OAuth credentials (one processor, not
    # an open-ended set), these are fixed Settings fields. Optional at the type level so a
    # deployment that hasn't activated billing yet (e.g. local dev) still boots —
    # BillingService raises BillingNotConfigured at first real use if any is missing, the same
    # "fail loudly at the point of use, not at import time" pattern
    # Settings.oauth_client_credentials() already established.
    polar_access_token: SecretStr | None = Field(default=None)
    polar_webhook_secret: SecretStr | None = Field(default=None)
    # "sandbox" (default — safe if unset) or "production". A misconfigured deployment should
    # never silently hit real production billing; the operator sets this explicitly to go
    # live, mirroring `environment`'s own safe-by-default convention above.
    polar_server: Literal["sandbox", "production"] = "sandbox"
    # Three Products, one per launch pricing tier (see docs/billing/BILLING_ARCHITECTURE.md's
    # "Tiered launch pricing") — each created in the Polar Dashboard, not by this codebase,
    # each with the same 7-day trial configured on it (Polar's trial lives on the Product, not
    # passed at checkout time). `polar_product_id` is the standard/base tier ($29, unlimited
    # capacity) — kept as the original field name since it's the tier every deployment must
    # configure; the other two are additive and optional so a deployment that hasn't set up
    # tiered pricing yet just sends every checkout to the standard product.
    polar_product_id: str | None = Field(default=None)
    polar_product_id_tier1: str | None = Field(default=None)  # "founding" — $9, first 5
    polar_product_id_tier2: str | None = Field(default=None)  # "early" — $19, next 10
    billing_checkout_success_url: str = Field(default="http://localhost:3000/billing/success")
    billing_portal_return_url: str = Field(default="http://localhost:3000/settings/billing")

    # --- Transactional email (Resend) — see app/core/email/. Used today only by
    # app/core/agent_lifecycle.py's cost-control sweep to notify a user their
    # conversation_finder agent was auto-disabled. Optional at the type level, same "fail
    # loudly at first use, not at import time" pattern as polar_access_token above — a
    # deployment that hasn't set these up yet still boots; ResendClient raises
    # EmailNotConfigured at first actual send attempt.
    resend_api_key: SecretStr | None = Field(default=None)
    resend_from_email: str | None = Field(default=None)

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
