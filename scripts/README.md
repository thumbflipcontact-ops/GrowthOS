# Scripts

Dev and ops scripts. Every script here should be safe to read before running — no script
performs a destructive action without a `--yes`/confirmation flag.

| Script | Purpose |
|---|---|
| `setup.sh` | First-time local setup: copies `.env.example` to `.env`, builds Docker images, runs migrations |
| `migrate.sh` | Runs Alembic migrations against the configured `DATABASE_URL` |
| `seed.py` | Seeds a local database with a demo org/project/agent-configs for development — never runs against staging/production |
| `lint.sh` | Runs `ruff`, `mypy`, `eslint` across `backend/`, `agents/`, `plugins/`, `frontend/` — the same checks CI runs |

## Status

Scripts are not yet implemented — this README documents intended scope so Phase 1
implementation has a clear target. See `ROADMAP.md`.
