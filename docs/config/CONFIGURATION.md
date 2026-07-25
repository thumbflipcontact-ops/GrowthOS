# Configuration Strategy

**Version 2** — `CREDENTIAL_ENCRYPTION_KEY` renamed `CREDENTIAL_MASTER_KEY` to match envelope
encryption (it now wraps per-connection data keys rather than encrypting credentials
directly — see `docs/security/SECURITY.md`); added `plugin_connections.config` as a third
config flavor.

## Three layers of configuration — don't conflate them

1. **Deployment configuration** — `.env`, one per environment (local, staging, production).
   Things like database URLs, Redis URL, LLM provider API keys, the encryption master key.
   Loaded via `pydantic-settings` into a typed `Settings` object, validated at process
   startup — a missing or malformed required variable fails fast at boot, not on the first
   request that happens to need it.
2. **Project/agent runtime configuration** — `projects.icp_config`, `projects.brand_voice`,
   `agent_configs.config`. Lives in the database, editable through the dashboard, takes
   effect without a deploy. Validated against each agent's own `config_schema`
   (`agents/<name>/config.py`).
3. **Plugin connection configuration** — `plugin_connections.config`, new in V2. Validated
   against the *owning plugin's* `config_schema` (declared in its manifest — see
   `docs/plugins/PLUGIN_ARCHITECTURE.md`), not an agent's. This is what lets a subreddit
   allowlist or an OAuth scope list live with the Reddit connection itself, instead of being
   duplicated into every agent config that happens to touch Reddit — see
   `docs/decisions/0009-plugin-config-schema-dynamic-ui.md`.

All three are genuinely different concerns and deliberately never conflated: layer 1 is
infrastructure, layers 2–3 are product/plugin data, and layer 3 specifically is owned by the
plugin author, not by core or by whichever agent happens to use that plugin.

## `.env` structure

```bash
# Database
DATABASE_URL=postgresql+asyncpg://growthos:***@localhost:5432/growthos

# Redis (cache, Arq broker)
REDIS_URL=redis://localhost:6379/0

# LLM providers
ANTHROPIC_API_KEY=***
OPENAI_API_KEY=***
LLM_PRIMARY_PROVIDER=anthropic          # see docs/decisions/0004-llm-provider-abstraction.md

# App
SECRET_KEY=***                           # session signing
CREDENTIAL_MASTER_KEY=***                # envelope-encryption master key — wraps each
                                          # plugin_connections row's per-connection data key,
                                          # see docs/security/SECURITY.md
ENVIRONMENT=local                        # local | staging | production
LOG_LEVEL=INFO

# Frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# OAuth2 plugin framework — see docs/auth/OAUTH2_ARCHITECTURE.md
OAUTH_CALLBACK_BASE_URL=http://localhost:8000     # the fixed redirect_uri origin registered
                                                   # with every OAuth-capable plugin's provider
OAUTH_FRONTEND_REDIRECT_URL=http://localhost:3000/settings/plugins
# {PLUGIN_KEY}_OAUTH_CLIENT_ID / _CLIENT_SECRET, one pair per installed OAuth-capable
# plugin — read directly from the environment, not a fixed Settings field (the plugin set
# is open-ended). E.g. REDDIT_OAUTH_CLIENT_ID / REDDIT_OAUTH_CLIENT_SECRET.
```

`.env.example` at the repo root is kept in sync with every variable `Settings` declares —
CI fails if they drift (a required setting with no corresponding `.env.example` entry, or
vice versa).

## Validation

```python
class Settings(BaseSettings):
    database_url: PostgresDsn
    redis_url: RedisDsn
    anthropic_api_key: SecretStr
    openai_api_key: SecretStr
    llm_primary_provider: Literal["anthropic", "openai"] = "anthropic"
    secret_key: SecretStr
    credential_master_key: SecretStr
    environment: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    oauth_callback_base_url: str = "http://localhost:8000"
    oauth_frontend_redirect_url: str = "http://localhost:3000/settings/plugins"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    def oauth_client_credentials(self, plugin_key: str) -> tuple[SecretStr, SecretStr]:
        """{PLUGIN_KEY}_OAUTH_CLIENT_ID/_CLIENT_SECRET, read from the environment directly —
        see docs/auth/OAUTH2_ARCHITECTURE.md §6 for why these aren't fixed Settings fields."""
```

Secrets are typed `SecretStr` so they never accidentally render in a stack trace, a repr, or
a log line — see `docs/logging/LOGGING.md` and `docs/security/SECURITY.md`.

## Per-environment differences

Only `ENVIRONMENT` and the values themselves differ across local/staging/production — the
same `Settings` schema and the same Docker images run in every environment (see
`docs/deployment/DEPLOYMENT.md`). No environment-specific code branches on `ENVIRONMENT`
except narrowly: enabling verbose debug logging and disabling HTTPS-only cookie flags for
local development.

## Project/agent/plugin config — schema-validated, not free-form

Even though `icp_config`, `brand_voice`, `agent_configs.config`, and (new in V2)
`plugin_connections.config` are stored as JSONB (chosen for per-project/per-agent/per-plugin
shape flexibility, see `docs/database/SCHEMA.md`), none of them are ever accepted or written
without validation against their owner's schema — an agent's `config_schema`
(`agents/<name>/config.py`), a plugin's `config_schema` (declared in its manifest, see
`docs/plugins/PLUGIN_ARCHITECTURE.md`), or a project-level schema for `icp_config`/
`brand_voice`. JSONB storage is a persistence choice, not a license to skip validation — the
API layer validates on every write, the owning agent/plugin validates again on read (defense
in depth against a config row written by an older schema version before a migration).

## Secrets management

`.env` is fine for local development. For staging/production, `.env` values are injected by
the deployment platform's secret store (see `docs/deployment/DEPLOYMENT.md`) rather than a
committed file — `.env` itself is `.gitignore`d; only `.env.example` (no real values) is
committed.
