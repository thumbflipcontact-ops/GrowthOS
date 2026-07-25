# Backend

FastAPI application — API layer, domain services, agent/plugin execution host. See
`ARCHITECTURE.md` at the repo root for how this fits into the overall system.

## Intended structure (Phase 1 implementation target)

```
backend/
├── app/
│   ├── main.py              FastAPI app factory, middleware, exception handlers
│   ├── core/
│   │   ├── config.py         Settings (pydantic-settings) — docs/config/CONFIGURATION.md
│   │   ├── errors.py          Domain exception hierarchy — docs/errors/ERROR_HANDLING.md
│   │   ├── security.py        Session/password handling — docs/auth/AUTHENTICATION.md
│   │   └── llm/                LLMProvider interface + Anthropic/OpenAI implementations
│   ├── api/
│   │   └── v1/                 One router module per resource — docs/api/API_DESIGN.md
│   ├── services/
│   │   ├── content_approval.py     The approval state machine — ARCHITECTURE.md §8
│   │   ├── knowledge_base.py
│   │   ├── agent_run.py
│   │   └── plugin_connection.py
│   ├── models/                  SQLAlchemy models mirroring database/schema.sql
│   ├── schemas/                  Pydantic request/response models
│   └── db/                       Session management, base declarative class
├── migrations/                    Alembic — generated from database/schema.sql design
├── tests/
│   ├── unit/
│   └── integration/
└── pyproject.toml
```

## Where agents and plugins live

Agent and plugin code is **not** under `backend/` — it lives in the top-level `agents/` and
`plugins/` packages, imported by `backend/app/services/agent_run.py` and the plugin registry.
This keeps the boundary between "the API/service layer" and "the independent, swappable
agent/plugin units" (`ARCHITECTURE.md` §2) visible in the folder structure itself, not just
in documentation.

## Status

Scaffolding only — see `ROADMAP.md` Phase 1 for what gets implemented first (auth, schema,
one plugin, two agents, the approval flow end-to-end).
