# Backend

FastAPI application — API layer, domain services, agent/plugin execution host. See
`ARCHITECTURE.md` at the repo root for how this fits into the overall system,
`PHASE_1_REPORT.md` (repo root) for what's implemented, tested, and verified as of Phase 1,
`docs/reviews/PLATFORM_IMPROVEMENT_REPORT.md` for the platform-developer-experience work done
between Phase 1 and the first real plugin, `docs/reviews/OAUTH_IMPLEMENTATION_REPORT.md` for
the generic OAuth2 framework built after that,
`docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md` for Phase 2A, and
`docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md` for Phase 2B.

## Structure (as implemented, through Phase 2B)

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
│   │   ├── llm/                    Generic LLMProvider interface — ADR 0004
│   │   │   ├── base.py               LLMProvider Protocol, LLMMessage/CompletionRequest/Result
│   │   │   ├── anthropic_provider.py  AnthropicProvider — Claude, the only implemented provider
│   │   │   ├── factory.py              build_llm_provider(settings) — resolves the primary provider
│   │   │   └── errors.py                LLMError hierarchy
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
│   │                                 (+ runs/trigger, runs), knowledge_items, content_items
│   │                                 (drafts — list/get only) routers
│   ├── services/
│   │   ├── auth_service.py         Register (org+user+membership bootstrap) / authenticate
│   │   ├── plugin_connection.py    Create/list a project's plugin connections, validating
│   │   │                             config against the plugin's config_schema
│   │   ├── oauth_connection.py     OAuth2 start/callback/disconnect orchestration
│   │   ├── agent_config.py         Create/update a project's agent_configs row, validating
│   │   │                             config against the agent's own config_schema
│   │   ├── knowledge_base.py       KnowledgeBaseClient — AgentContext.knowledge_base's first
│   │   │                             concrete implementation (dedup-then-upsert by URL)
│   │   └── content_drafts.py        ContentDraftClient — AgentContext.content's first concrete
│   │                                  implementation (always writes status="draft")
│   ├── models/                      SQLAlchemy models mirroring database/schema.sql (all 17 tables)
│   ├── schemas/                      Pydantic request/response models
│   ├── repositories/                  One per aggregate — org, user/membership, project,
│   │                                    plugin (catalog/connection), agent (config/run), event,
│   │                                    knowledge (knowledge_items), content (content_items)
│   ├── jobs/                           Arq WorkerSettings: agent_runs.py (schedule-triggered —
│   │                                    real body since Phase 2A), events.py (subscription-
│   │                                    triggered `run_agent_for_event` — real body since
│   │                                    Phase 2B, identical AgentContext-construction pattern),
│   │                                    publish.py (still a placeholder), oauth_refresh.py
│   └── scheduler.py                    Scheduler process entrypoint (`python -m app.scheduler`)
├── migrations/                          Alembic — matches database/schema.sql
├── tests/
│   ├── conftest.py                      pgserver (embedded Postgres) + fakeredis fixtures
│   ├── unit/
│   └── integration/
└── pyproject.toml
```

**Explicitly not present**, per ROADMAP.md Phase 2B scope (business logic still deferred):
`services/content_approval.py` (the actual approve/reject state-machine service and API
endpoints — Phase 2C). `core/llm/` and `services/knowledge_base.py`/`content_drafts.py`
**now exist** — Conversation Finder (Phase 2A) and Content Agent (Phase 2B) are the agents
that needed them; see their implementation reports. `core/llm/factory.py` only builds
Claude — OpenAI (ADR 0004's documented secondary provider) has no implementation yet and
raises `LLMProviderNotConfigured` if selected. `core/llm/base.py`'s `LLMProvider` has no
`embed()` method yet — nothing needs `knowledge_items.embedding` populated. Credential wiring
exists for `auth_type="oauth2"` but not yet for `api_key`/`session_credentials` — no request
path writes `credentials_encrypted` for those auth types. `jobs/publish.py`'s body is still a
placeholder — the only job left with no real agent to invoke it, since publishing only
happens after `ContentApprovalService` (Phase 2C) exists.

## Where agents and plugins live

Agent and plugin code is **not** under `backend/` — the SDKs live in the top-level
`agents/_shared/` and `plugins/_shared/` packages (Protocols, manifest/subscription
dataclasses), imported by `backend/app/core/`. This keeps the boundary between "the
API/service layer" and "the independent, swappable agent/plugin units" (`ARCHITECTURE.md`
§2) visible in the folder structure itself, not just in documentation. `plugins/reddit/` is
the first real plugin (see `docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md`);
`agents/conversation_finder/` is the first real agent (see
`docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md`), `agents/content_agent/` is the
second (see `docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md`) — both loaded by
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
