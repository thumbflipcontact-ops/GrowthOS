# Scripts

Dev and ops scripts. Every script here is safe to read before running — no script performs a
destructive action without a confirmation step, and `seed.py` refuses to run against
anything but a local environment.

Written in Python (not shell) so the same script works unmodified on Windows, macOS, and
Linux — no separate `.sh`/`.ps1` variants to keep in sync. This project does not use Docker
for local development (see `docker/README.md` for the Docker-based alternative, which
remains fully supported and unchanged for anyone who prefers it).

| Script | Purpose |
|---|---|
| `setup.py` | First-time local setup: installs `uv`, provisions a Python 3.12 virtualenv at `backend/.venv` (pgserver — this project's embedded-Postgres dependency, see `docs/testing/TESTING.md` — has no Python 3.13 Windows wheel yet), installs backend dependencies, copies `.env.example` to `.env` |
| `migrate.py` | Runs Alembic migrations against `DATABASE_URL` — `python scripts/migrate.py` (upgrade to head) or pass through any Alembic subcommand, e.g. `python scripts/migrate.py revision --autogenerate -m "..."` |
| `seed.py` | Seeds a local database with a demo org/user/project — refuses to run unless `ENVIRONMENT=local` |
| `lint.py` | Runs `ruff` and `mypy --strict` against `backend/` — the same checks CI runs |
| `../backend/scripts/dev_postgres.py` | Runs a real, embedded Postgres instance for local development without Docker — prints `DATABASE_URL`, stays running until Ctrl+C. Backend-specific, so it lives under `backend/scripts/` rather than here. |

## Quickstart

```bash
python scripts/setup.py
# in one terminal: start a local Postgres (or point DATABASE_URL at a real one, e.g. via
# docker/docker-compose.yml if you prefer Docker)
cd backend && .venv/Scripts/python scripts/dev_postgres.py   # Windows
cd backend && .venv/bin/python scripts/dev_postgres.py       # macOS/Linux
# in another terminal:
python scripts/migrate.py
python scripts/seed.py
python scripts/lint.py
```

## Status

Implemented as of Phase 1 — see `ARCHITECTURE_FREEZE.md` and `ROADMAP.md` Phase 1 for what
this environment supports (platform foundation only; no agent business logic).
