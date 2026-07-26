# Deployment Guide (Internal Beta)

The full deployment reference is `docs/deployment/DEPLOYMENT.md` — services, environments,
CI/CD, migrations, process supervision, TLS, observability, backups. This document is the
short, beta-specific path through it: what to actually do to run GrowthOS for real, today,
as a single operator.

## The recommended path for beta: one host, no Docker

`docs/deployment/DEPLOYMENT.md` documents two supported ways to run GrowthOS (Docker Compose
and bare processes) and is explicit that the Docker Compose path **has never been run end to
end** — its own file header says so. For internal beta, use the non-Docker path; it's what
this project's own development has actually exercised throughout, including everything
verified while building this beta-readiness pass (`docs/reviews/INTERNAL_BETA_READINESS_REPORT.md`).

Six long-lived processes, each in its own terminal or process-supervisor entry:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000     # backend
python -m app.scheduler                              # scheduler
arq app.jobs.agent_runs.WorkerSettings                # worker-agents
arq app.jobs.events.WorkerSettings                      # worker-events
arq app.jobs.publish.WorkerSettings                       # worker-publish
arq app.jobs.oauth_refresh.WorkerSettings                  # worker-oauth-refresh
```

Plus a real Postgres (with `pgvector`) and a real Redis — see
`docs/beta/SETUP_GUIDE.md` §3 for a Docker-free way to get both running locally.

## Before you leave it running unattended

1. **`python scripts/check_env.py`** — passes with 0 failures.
2. **Migrations are current** — `python scripts/migrate.py`, or trust the fact that every
   process now refuses to start against a stale schema (`app/core/migration_check.py`) rather
   than silently misbehaving.
3. **`GET /health` returns 200** — this actually checks Postgres and Redis reachability now,
   not just "the process is up" (`docs/reviews/PRODUCTION_READINESS_REVIEW.md` O1).
4. **A process supervisor restarts anything that crashes.** GrowthOS does not ship one — pick
   whichever fits your host (systemd, a process manager, Docker's `restart:` policy if you do
   switch to Docker) and *verify* it actually restarts a killed process before trusting it —
   see `docs/deployment/DEPLOYMENT.md`'s "Process supervision" section.
5. **Backups are a manual procedure, not automation** (a deliberate choice — see
   `docs/reviews/PRODUCTION_HARDENING_REPORT.md` §4). At minimum, run this on a schedule you
   actually remember:
   ```bash
   pg_dump --format=custom --file="growthos-$(date +%Y%m%d-%H%M%S).dump" "$DATABASE_URL"
   ```
   Store the result somewhere other than the same disk. See `docs/deployment/DEPLOYMENT.md`'s
   "Backups" section for the restore command too.
6. **Set `SENTRY_DSN`** (optional, but recommended once you're leaving this genuinely
   unattended) — the single narrowest, most valuable observability piece this project has:
   an agent run or a publish attempt failing silently in a background worker with nothing but
   a local log line is the worst failure mode for a system whose entire point is "runs
   unattended." See `app/core/observability.py` and `docs/config/CONFIGURATION.md`.

## What's still genuinely missing for a "real" production deployment

Not a beta blocker, but don't mistake beta-readiness for production-readiness at scale — see
`docs/beta/KNOWN_LIMITATIONS.md` for the full list. The short version: no CI pipeline, no
automated backups, no process-supervision config shipped, the Docker path is unverified, and
full OpenTelemetry/Prometheus observability doesn't exist (only the narrower Sentry piece
above does). None of these block *you*, one operator, running this against your own accounts
under your own supervision — they matter more the moment a second person's data or a second
unattended-for-weeks deployment enters the picture.
