# Backend

FastAPI application — API layer, domain services, agent/plugin execution host. See
`ARCHITECTURE.md` at the repo root for how this fits into the overall system,
`PHASE_1_REPORT.md` (repo root) for what's implemented, tested, and verified as of Phase 1,
`docs/reviews/PLATFORM_IMPROVEMENT_REPORT.md` for the platform-developer-experience work done
between Phase 1 and the first real plugin, and `docs/reviews/OAUTH_IMPLEMENTATION_REPORT.md`
for the generic OAuth2 framework built after that.

## Structure (as implemented, Phase 1 + the Platform Readiness / OAuth2 passes)

```
backend/
├── app/
│   ├── main.py                 FastAPI app factory, lifespan (DB engine, plugin catalog
│   │                             discovery), exception handlers, request-id middleware
│   ├── core/
│   │   ├── config.py            Settings (pydantic-settings) — docs/config/CONFIGURATION.md
│   │   ├── logging.py            structlog setup + secret redaction — docs/logging/
│   │   ├── errors.py             Domain exception hierarchy — docs/errors/ERROR_HANDLING.md
│   │   ├── security.py           Password hashing, session tokens — docs/auth/
│   │   ├── crypto.py              Envelope encryption (ADR 0010) — the actual encrypt/decrypt
│   │   │                            primitive; OAuth2 is its first real consumer
│   │   ├── db.py                  Async engine/session factory
│   │   ├── events.py              EventPublisher (transactional outbox) — ARCHITECTURE.md §7
│   │   ├── subscriptions.py       Agent subscription discovery (mirrors plugin_catalog.py)
│   │   ├── dispatcher.py          EventDispatcher core logic — ARCHITECTURE.md §7
│   │   ├── scheduler.py           Cron due-check logic — docs/jobs/BACKGROUND_JOBS.md
│   │   ├── plugin_catalog.py      Manifest discovery/scanning — docs/plugins/
│   │   ├── plugin_registry.py     Per-project capability-checked plugin resolution +
│   │   │                            credential decryption (docs/auth/OAUTH2_ARCHITECTURE.md)
│   │   ├── agent_registry.py      Loads a specific installed agent by key, for execution —
│   │   │                            docs/agents/AGENT_ARCHITECTURE.md
│   │   └── oauth/                 Generic OAuth2 subsystem — docs/auth/OAUTH2_ARCHITECTURE.md
│   │       ├── pkce.py              RFC 7636 code_verifier/code_challenge
│   │       ├── state.py             Signed, stateless CSRF state token
│   │       ├── client.py            Provider-agnostic authorize/exchange/refresh/revoke
│   │       ├── refresh.py           The token-refresh sweep's core logic
│   │       └── errors.py            OAuth-flow exception hierarchy
│   ├── api/
│   │   ├── deps.py                get_db, get_current_user, require_project_access/org_access,
│   │   │                             get_plugin_catalog, get_settings_dep, get_arq_redis
│   │   └── v1/                     health, auth, projects, plugins (catalog),
│   │                                 plugin_connections (+ oauth/start, oauth/disconnect),
│   │                                 oauth (the global callback route), agent_configs
│   │                                 (+ runs/trigger, runs), knowledge_items routers
│   ├── services/
│   │   ├── auth_service.py         Register (org+user+membership bootstrap) / authenticate
│   │   ├── plugin_connection.py    Create/list a project's plugin connections, validating
│   │   │                             config against the plugin's config_schema
│   │   ├── oauth_connection.py     OAuth2 start/callback/disconnect orchestration
│   │   ├── agent_config.py         Create/update a project's agent_configs row, validating
│   │   │                             config against the agent's own config_schema
│   │   └── knowledge_base.py       KnowledgeBaseClient — AgentContext.knowledge_base's first
│   │                                 concrete implementation (dedup-then-upsert by URL)
│   ├── models/                      SQLAlchemy models mirroring database/schema.sql (all 17 tables)
│   ├── schemas/                      Pydantic request/response models
│   ├── repositories/                  One per aggregate — org, user/membership, project,
│   │                                    plugin (catalog/connection), agent (config/run), event,
│   │                                    knowledge (knowledge_items)
│   ├── jobs/                           Arq WorkerSettings: agent_runs.py (real body — loads an
│   │                                    agent_config, builds AgentContext, runs the agent,
│   │                                    records the outcome), events.py, publish.py,
│   │                                    oauth_refresh.py
│   └── scheduler.py                    Scheduler process entrypoint (`python -m app.scheduler`)
├── migrations/                          Alembic — matches database/schema.sql
├── tests/
│   ├── conftest.py                      pgserver (embedded Postgres) + fakeredis fixtures
│   ├── unit/
│   └── integration/
└── pyproject.toml
```

**Explicitly not present**, per ROADMAP.md Phase 2A scope (business logic still deferred):
`services/content_approval.py` (Approval Inbox / publish worker — Phase 2B+), `core/llm/`
(AI provider clients — config plumbing for them exists in `core/config.py`, no client
implementation; `AgentContext.llm` stays typed `object` until one exists). `services/
knowledge_base.py` **now exists** — Conversation Finder (Phase 2A) is the first agent that
needed it; see `docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md`. Credential wiring
exists for `auth_type="oauth2"` (the flow above) but not yet for `api_key`/
`session_credentials` — no request path writes `credentials_encrypted` for those auth types.
The publish job body in `jobs/publish.py` and the subscription-triggered `run_agent_for_event`
in `jobs/events.py` are still placeholders — `jobs/agent_runs.py`'s schedule-triggered
`run_scheduled_agent` is the one job body wired for real so far, because Conversation Finder
(schedule-only, no subscriptions) is the only agent that exists.

## Where agents and plugins live

Agent and plugin code is **not** under `backend/` — the SDKs live in the top-level
`agents/_shared/` and `plugins/_shared/` packages (Protocols, manifest/subscription
dataclasses), imported by `backend/app/core/`. This keeps the boundary between "the
API/service layer" and "the independent, swappable agent/plugin units" (`ARCHITECTURE.md`
§2) visible in the folder structure itself, not just in documentation. `plugins/reddit/` is
the first real plugin (see `docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md`);
`agents/conversation_finder/` is the first real agent (see
`docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md`) — loaded by
`app/core/agent_registry.py`'s import-by-key convention, the agent-side mirror of
`app/core/plugin_registry.py`'s plugin loading. `plugins/dummy/` remains a test-only fixture
proving the plugin discovery mechanism works (see its `README.md`, and its own `tests/`), not
a template to build a real integration from without reading `docs/plugins/QUICKSTART.md` and
`docs/plugins/PLUGIN_ARCHITECTURE.md` first. `python scripts/new_plugin.py <name>` scaffolds a
new plugin package's boilerplate.

## Status

Implemented and tested — see `PHASE_1_REPORT.md`. Run the test suite:
`cd backend && .venv/Scripts/python -m pytest -p no:cov` (Windows) or
`.venv/bin/python -m pytest -p no:cov` (macOS/Linux). See `scripts/README.md` for setup.
