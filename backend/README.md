# Backend

FastAPI application — API layer, domain services, agent/plugin execution host. See
`ARCHITECTURE.md` at the repo root for how this fits into the overall system, and
`PHASE_1_REPORT.md` (repo root) for what's implemented, tested, and verified as of Phase 1.

## Structure (as implemented, Phase 1)

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
│   │   ├── db.py                  Async engine/session factory
│   │   ├── events.py              EventPublisher (transactional outbox) — ARCHITECTURE.md §7
│   │   ├── subscriptions.py       Agent subscription discovery (mirrors plugin_catalog.py)
│   │   ├── dispatcher.py          EventDispatcher core logic — ARCHITECTURE.md §7
│   │   ├── scheduler.py           Cron due-check logic — docs/jobs/BACKGROUND_JOBS.md
│   │   ├── plugin_catalog.py      Manifest discovery/scanning — docs/plugins/
│   │   └── plugin_registry.py     Per-project capability-checked plugin resolution
│   ├── api/
│   │   ├── deps.py                get_db, get_current_user, require_project_access/org_access
│   │   └── v1/                     health, auth, projects, plugins (catalog) routers
│   ├── services/
│   │   └── auth_service.py         Register (org+user+membership bootstrap) / authenticate
│   ├── models/                      SQLAlchemy models mirroring database/schema.sql (all 17 tables)
│   ├── schemas/                      Pydantic request/response models
│   ├── repositories/                  One per aggregate — org, user/membership, project,
│   │                                    plugin (catalog/connection), agent (config/run), event
│   ├── jobs/                           Arq WorkerSettings: agent_runs.py, events.py, publish.py
│   └── scheduler.py                    Scheduler process entrypoint (`python -m app.scheduler`)
├── migrations/                          Alembic — one migration, matches database/schema.sql
├── tests/
│   ├── conftest.py                      pgserver (embedded Postgres) + fakeredis fixtures
│   ├── unit/
│   └── integration/
└── pyproject.toml
```

**Explicitly not present**, per ROADMAP.md Phase 1 scope (business logic, not foundation):
`services/content_approval.py`, `services/knowledge_base.py`, `services/plugin_connection.py`
(config-schema validation logic), `core/llm/` (AI provider clients — config plumbing for them
exists in `core/config.py`, no client implementation). The real agent-run and publish job
bodies in `jobs/` are placeholders for the same reason — the queue plumbing around them is
real and tested; what a job *does* once triggered is Phase 2+.

## Where agents and plugins live

Agent and plugin code is **not** under `backend/` — the SDKs live in the top-level
`agents/_shared/` and `plugins/_shared/` packages (Protocols, manifest/subscription
dataclasses), imported by `backend/app/core/`. This keeps the boundary between "the
API/service layer" and "the independent, swappable agent/plugin units" (`ARCHITECTURE.md`
§2) visible in the folder structure itself, not just in documentation. No real agent or
plugin package exists yet — `plugins/dummy/` is a test-only fixture proving the discovery
mechanism works (see its `README.md`), not a template to build a real integration from
without reading `docs/plugins/PLUGIN_ARCHITECTURE.md` first.

## Status

Implemented and tested — see `PHASE_1_REPORT.md`. Run the test suite:
`cd backend && .venv/Scripts/python -m pytest -p no:cov` (Windows) or
`.venv/bin/python -m pytest -p no:cov` (macOS/Linux). See `scripts/README.md` for setup.
