"""Deployment configuration — see docs/config/CONFIGURATION.md.

Loaded once from environment/.env into a typed, validated Settings object. A missing or
malformed required variable fails fast at process startup, not on the first request that
happens to need it.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database ---
    database_url: PostgresDsn

    # --- Redis (Arq broker, cache, rate limiting, event dispatch) ---
    redis_url: RedisDsn

    # --- LLM providers — see docs/decisions/0004-llm-provider-abstraction.md.
    # Config plumbing only in Phase 1: no provider client is implemented yet
    # (explicitly excluded from Phase 1 scope, see ROADMAP.md), but the settings exist so
    # .env / .env.example stay the single source of truth for what a full deployment needs.
    anthropic_api_key: SecretStr
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

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_local(self) -> bool:
        return self.environment == "local"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — Settings() runs env parsing/validation once per process."""
    return Settings()  # type: ignore[call-arg]  # values come from env/.env at runtime
