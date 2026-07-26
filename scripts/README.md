# Scripts

Dev and ops scripts. Every script here is safe to read before running — no script performs a
destructive action without a confirmation step, `seed.py` refuses to run against anything but
a local environment, and `onboard.py` never writes anything until you've answered every
prompt.

Written in Python (not shell) so the same script works unmodified on Windows, macOS, and
Linux — no separate `.sh`/`.ps1` variants to keep in sync. This project does not use Docker
for local development (see `docker/README.md` for the Docker-based alternative, which
remains fully supported and unchanged for anyone who prefers it).

Scripts that import `backend/app` code directly (`check_env.py`, `status.py`, `onboard.py`,
`seed.py`) automatically re-exec themselves under `backend/.venv`'s Python if you ran them
with a different one — see `_bootstrap.py`. You can still always run them explicitly via
`backend/.venv/Scripts/python.exe scripts/<name>.py` (Windows) /
`backend/.venv/bin/python scripts/<name>.py` (macOS/Linux) if you prefer.

| Script | Purpose |
|---|---|
| `setup.py` | First-time local setup: installs `uv`, provisions a Python 3.12 virtualenv at `backend/.venv` (pgserver — this project's embedded-Postgres dependency, see `docs/testing/TESTING.md` — has no Python 3.13 Windows wheel yet), installs backend dependencies, copies `.env.example` to `.env` |
| `check_env.py` | **Run this first, and any time something seems broken.** Validates your `.env`, tests real Postgres/Redis connectivity, checks the database is at the expected migration revision, confirms the plugin catalog loads, and flags placeholder secrets/API keys — see `docs/beta/TROUBLESHOOTING_GUIDE.md`. `--live-llm-check` additionally makes one real (billed) Anthropic API call to verify the key actually works. |
| `migrate.py` | Runs Alembic migrations against `DATABASE_URL` (loaded from `.env` automatically) — `python scripts/migrate.py` (upgrade to head) or pass through any Alembic subcommand, e.g. `python scripts/migrate.py revision --autogenerate -m "..."` |
| `onboard.py` | **Interactive first-run wizard.** Creates your organization, owner account, and first project, then prints the exact next steps (with real project/org IDs filled in) — see `docs/beta/FIRST_RUN_CHECKLIST.md`. Safe to re-run. |
| `seed.py` | Seeds a local database with a *demo* org/user (`demo-org` / `founder@demo.local`, a well-known throwaway password) for quick local testing — refuses to run unless `ENVIRONMENT=local`. Use `onboard.py` instead for a real account. |
| `status.py` | Read-only operational status dashboard — plugin connections, agent configs, recent runs, content-item counts, event-dispatch backlog — without hand-writing SQL or curl-ing every endpoint. `--project SLUG` narrows to one project. |
| `lint.py` | Runs `ruff` and `mypy` (project's own `strict = true` config) against `backend/` — the same checks CI runs |
| `new_plugin.py` | Scaffolds a new plugin package at `plugins/<name>/` — manifest, `plugin.py` stub, `pyproject.toml` with the entry-point + packaging boilerplate already correct, `README.md`, `tests/`. See `docs/plugins/QUICKSTART.md`. |
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
python scripts/check_env.py    # confirm everything's actually reachable before going further
python scripts/onboard.py      # create your real org/user/project (or scripts/seed.py for a quick demo one)
python scripts/lint.py
```

To actually run the app — the backend API, the scheduler, and the four background workers —
see `docs/deployment/DEPLOYMENT.md`'s "Non-Docker deployment" section for the exact commands;
none of them are wrapped in a script here since they're all plain, already-short
`uvicorn`/`python -m`/`arq` invocations. `docs/beta/FIRST_RUN_CHECKLIST.md` walks through the
entire sequence above plus what comes after (connecting Reddit, configuring agents,
approving your first draft) end to end.

## Status

Implemented as of Phase 2D (Production Hardening) plus the Internal Beta operational tooling
above — see `ROADMAP.md` and `docs/reviews/INTERNAL_BETA_READINESS_REPORT.md` for the current
state of the platform these scripts operate.
