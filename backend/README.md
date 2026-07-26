# Backend

FastAPI application — API layer, domain services, agent/plugin execution host. See
`ARCHITECTURE.md` at the repo root for how this fits into the overall system,
`PHASE_1_REPORT.md` (repo root) for what's implemented, tested, and verified as of Phase 1,
`docs/reviews/PLATFORM_IMPROVEMENT_REPORT.md` for the platform-developer-experience work done
between Phase 1 and the first real plugin, `docs/reviews/OAUTH_IMPLEMENTATION_REPORT.md` for
the generic OAuth2 framework built after that,
`docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md` for Phase 2A,
`docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md` for Phase 2B, and
`docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md` +
`docs/reviews/PUBLISHING_WORKFLOW_IMPLEMENTATION_REPORT.md` for Phase 2C, and
`docs/reviews/PRODUCTION_READINESS_REVIEW.md` + `docs/reviews/PRODUCTION_HARDENING_REPORT.md`
for Phase 2D.

## Structure (as implemented, through Phase 2D)

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
│   │   ├── db.py                  Async engine/session factory — pool_size/max_overflow now
│   │   │                            explicit params (Phase 2D, docs/scalability/SCALABILITY.md)
│   │   ├── events.py              EventPublisher (transactional outbox) — ARCHITECTURE.md §7
│   │   ├── subscriptions.py       Agent subscription discovery (mirrors plugin_catalog.py)
│   │   ├── dispatcher.py          EventDispatcher core logic — ARCHITECTURE.md §7. Commits
│   │   │                            dispatched_at per event since Phase 2D, not once per batch
│   │   ├── scheduler.py           Cron due-check logic — docs/jobs/BACKGROUND_JOBS.md
│   │   ├── plugin_catalog.py      Manifest discovery/scanning — docs/plugins/
│   │   ├── plugin_registry.py     Per-project capability-checked plugin resolution +
│   │   │                            credential decryption (docs/auth/OAUTH2_ARCHITECTURE.md)
│   │   ├── agent_registry.py      Loads a specific installed agent by key, for execution —
│   │   │                            docs/agents/AGENT_ARCHITECTURE.md
│   │   ├── job_retry.py            arq.worker.Retry + shared backoff formula every job body
│   │   │                            re-raises with — Phase 2D, docs/reviews/
│   │   │                            PRODUCTION_READINESS_REVIEW.md §3.1
│   │   ├── migration_check.py      Fail-fast startup check that the DB is at the code's
│   │   │                            expected Alembic head — Phase 2D
│   │   ├── observability.py        Optional (SENTRY_DSN-gated) error tracking — Phase 2D
│   │   ├── rate_limit.py            Generic in-process token-bucket limiter — Phase 2D, first
│   │   │                             used by POST /auth/login
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
│   │   │                             get_plugin_catalog, get_settings_dep, get_arq_redis,
│   │   │                             get_login_ip_limiter/get_login_account_limiter (Phase 2D)
│   │   └── v1/                     health (now checks DB+Redis, Phase 2D), auth (login now
│   │                                 rate-limited, Phase 2D), projects, plugins (catalog),
│   │                                 plugin_connections (+ oauth/start, oauth/disconnect),
│   │                                 oauth (the global callback route), agent_configs
│   │                                 (+ runs/trigger, runs), knowledge_items, content_items
│   │                                 (list/get, + approve/reject/archive/retry-publish/
│   │                                 publish-attempts since Phase 2C) routers
│   ├── services/
│   │   ├── auth_service.py         Register (org+user+membership bootstrap) / authenticate
│   │   ├── plugin_connection.py    Create/list a project's plugin connections, validating
│   │   │                             config against the plugin's config_schema
│   │   ├── oauth_connection.py     OAuth2 start/callback/disconnect orchestration
│   │   ├── agent_config.py         Create/update a project's agent_configs row, validating
│   │   │                             config against the agent's own config_schema
│   │   ├── knowledge_base.py       KnowledgeBaseClient — AgentContext.knowledge_base's first
│   │   │                             concrete implementation (dedup-then-upsert by URL)
│   │   ├── content_drafts.py        ContentDraftClient — AgentContext.content's first concrete
│   │   │                              implementation. `create_draft` always writes
│   │   │                              status="draft"; `submit_for_review` (Phase 2C) is the
│   │   │                              separate, explicit self-check/auto-advance step an agent
│   │   │                              calls right after — see content_self_check.py below.
│   │   ├── content_self_check.py     run_self_check() — length/banned-phrase gate a draft must
│   │   │                              pass before ContentDraftClient.submit_for_review advances
│   │   │                              it to pending_review. Phase 2C.
│   │   └── content_approval.py       ContentApprovalService — approve/reject/archive, one
│   │                                    version-guarded atomic UPDATE per transition
│   │                                    (ARCHITECTURE.md §8). Phase 2C.
│   ├── models/                      SQLAlchemy models mirroring database/schema.sql (all 18
│   │                                  tables — content_publish_attempts is new in Phase 2C)
│   ├── schemas/                      Pydantic request/response models
│   ├── repositories/                  One per aggregate — org, user/membership, project,
│   │                                    plugin (catalog/connection), agent (config/run), event,
│   │                                    knowledge (knowledge_items), content (content_items,
│   │                                    + ContentPublishAttemptRepository since Phase 2C)
│   ├── jobs/                           Arq WorkerSettings: agent_runs.py (schedule-triggered —
│   │                                    real body since Phase 2A), events.py (subscription-
│   │                                    triggered `run_agent_for_event` — real body since
│   │                                    Phase 2B, identical AgentContext-construction pattern;
│   │                                    dispatch_domain_events' enqueue is job-id-keyed since
│   │                                    Phase 2D), publish.py (real body since Phase 2C — the
│   │                                    only caller of any plugin's `Publishable.publish()`,
│   │                                    genuinely retried up to 3 times since Phase 2D — see
│   │                                    job_retry.py above — idempotency-keyed by
│   │                                    content_item.id, and reconciles rather than re-posts
│   │                                    if a prior successful attempt is found), oauth_refresh.py
│   └── scheduler.py                    Scheduler process entrypoint (`python -m app.scheduler`)
├── migrations/                          Alembic — matches database/schema.sql
├── tests/
│   ├── conftest.py                      pgserver (embedded Postgres) + fakeredis fixtures
│   ├── unit/
│   └── integration/
└── pyproject.toml
```

**Explicitly not present**: `core/llm/factory.py` only builds Claude — OpenAI (ADR 0004's
documented secondary provider) has no implementation yet and raises
`LLMProviderNotConfigured` if selected. `core/llm/base.py`'s `LLMProvider` has no `embed()`
method yet — nothing needs `knowledge_items.embedding` populated. Credential wiring exists
for `auth_type="oauth2"` but not yet for `api_key`/`session_credentials` — no request path
writes `credentials_encrypted` for those auth types. No scheduling, no LinkedIn/X/Slack/email
plugins, no frontend, no analytics dashboards, no full OpenTelemetry/Prometheus stack (a
narrower baseline error-tracking integration exists instead, see
`docs/reviews/PRODUCTION_HARDENING_REPORT.md`) — see `ROADMAP.md` for what's actually next.

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
