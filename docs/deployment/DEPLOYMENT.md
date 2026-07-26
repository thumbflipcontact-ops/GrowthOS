# Deployment Strategy

## v1 target: single-host, one operator

A single VPS (or equivalent) running a handful of long-lived processes is the right
deployment shape for a single-operator system with a modest number of background workers and
moderate traffic — not Kubernetes. See `docs/decisions/` for the reasoning if this is ever
revisited; the short version is that Kubernetes' operational overhead buys nothing until
there's a real multi-tenant scaling requirement (Phase 4, see `ROADMAP.md`), and premature
infrastructure complexity is a cost paid every day, not just once.

Two supported ways to run that single host, kept in parity:

- **Docker Compose** (`docker/docker-compose.yml`) — described below in "Services." As of
  this writing it has never actually been run end to end (see the file's own header comment);
  treat it as a documented starting point, not a verified path, until someone does a real
  `docker compose build && docker compose up` pass and fixes whatever Docker-specific
  wrinkle turns up (there is usually at least one).
- **Bare processes, no Docker** — this project's actual local-dev and (currently) real
  deployment mode; see "Non-Docker deployment" below. Every process is a plain Python
  invocation; nothing here is Docker-specific.

Both run the exact same code and the exact same six long-lived processes — the only
difference is what supervises and networks them.

## Services

```
backend             FastAPI app (uvicorn) — also hosts the plugin_catalog manifest scan at
                       startup, see docs/plugins/PLUGIN_ARCHITECTURE.md
frontend             Next.js app (Phase 2 — no code yet)
scheduler             Polls agent_configs, enqueues due schedule-triggered jobs
worker-agents          Arq worker, agent-runs queue
worker-events           Arq worker, event-dispatch queue AND the periodic dispatcher job
                          itself (docs/jobs/BACKGROUND_JOBS.md) — kept separate from
                          worker-agents so a backlog of agent runs never delays event
                          dispatch latency
worker-publish            Arq worker, publish-jobs queue (separate pool — see
                            docs/jobs/BACKGROUND_JOBS.md)
worker-oauth-refresh       Arq worker, periodic OAuth token-refresh sweep
                            (app/jobs/oauth_refresh.py, docs/auth/OAUTH2_ARCHITECTURE.md §7)
                            — previously undocumented and unrun anywhere
                            (docs/reviews/PRODUCTION_READINESS_REVIEW.md O12); without this
                            process, every connected OAuth plugin (Reddit) eventually
                            degrades to `expired` purely because nothing invoked the refresh.
postgres                    Postgres + pgvector (system of record, incl. domain_events outbox)
redis                        Arq broker (job execution + event dispatch), cache, rate limiting
```

No new *kind* of worker beyond the first one — `worker-events`, `worker-publish`, and
`worker-oauth-refresh` are each just another Arq worker process, identical in shape to
`worker-agents`, pointed at a different queue/module. This is the concrete payoff of choosing
Arq/Postgres-outbox over a dedicated message broker (`ARCHITECTURE.md` §7): every new job
category fits the existing deployment topology instead of requiring new infrastructure.

## Non-Docker deployment

Every process is a plain command against `backend/.venv`'s Python — no container runtime
required. Set every variable `backend/app/core/config.py` requires (see
`docs/config/CONFIGURATION.md`; `.env.example` lists them) in the process environment or a
`.env` file, then run each of the six processes below (each stays running; use whatever
process supervisor you choose — see "Process supervision" — to keep them up):

```bash
# from backend/, with .venv activated (or use .venv/Scripts/python / .venv/bin/python directly)
uvicorn app.main:app --host 0.0.0.0 --port 8000     # backend
python -m app.scheduler                              # scheduler
arq app.jobs.agent_runs.WorkerSettings                # worker-agents
arq app.jobs.events.WorkerSettings                      # worker-events
arq app.jobs.publish.WorkerSettings                       # worker-publish
arq app.jobs.oauth_refresh.WorkerSettings                  # worker-oauth-refresh
```

`arq` is installed as a console script into `backend/.venv` alongside the rest of the
dependencies (`scripts/setup.py`) — no separate installation step. Postgres and Redis
themselves aren't part of this list; run real installations of both (see
`backend/scripts/dev_postgres.py` for a Docker-free embedded option suitable for local
development, not production) and point `DATABASE_URL`/`REDIS_URL` at them.

Before starting `backend` for the first time (or after pulling new migrations), run
`python scripts/migrate.py` (from the repo root) — every process now also verifies at its own
startup that the database is at the migration revision the code expects
(`app/core/migration_check.py`, added per
docs/reviews/PRODUCTION_READINESS_REVIEW.md O7) and refuses to start otherwise, so a
forgotten migration fails loudly and immediately rather than degrading into confusing
first-query errors later.

## Environments

| Environment | Purpose | Notes |
|---|---|---|
| Local | Development | Docker-free by default (`scripts/README.md`); `docker compose up` remains a supported alternative |
| Staging | Pre-production validation | Same code, separate `.env`, separate database — used to validate a new agent/plugin against real (but non-production-critical) external calls before it touches the live ScoutSEO project |
| Production | Live | Same build as staging, promoted after staging validation, not rebuilt from source at deploy time |

## CI/CD

1. PR opened → lint + unit/contract/integration tests (`docs/testing/TESTING.md`).
2. Merge to `main` → build/tag the release artifact, run the end-to-end suite against it.
3. Manual promotion (a deliberate step, not automatic) deploys to staging, then production —
   this system controls real, external-facing publishing actions, so an accidental bad deploy
   has a higher blast radius than a typical internal tool; the promotion step stays manual
   until there's enough deployment history to trust automating it.

**Not yet built**: no CI pipeline (`.github/` or equivalent) exists in this repository yet —
the steps above describe the intended shape, not a running system. Tracked as remaining work,
not silently assumed complete (docs/reviews/PRODUCTION_HARDENING_REPORT.md).

## Migrations

Alembic migrations run as a deliberate, one-off step — `python scripts/migrate.py` (or
`python scripts/migrate.py upgrade head` explicitly) — before the new `backend` build starts
serving traffic, never as an app-startup side effect; a migration failure should block the
deploy loudly, not degrade into the app half-starting. Since that step is easy to forget in
practice, every process additionally refuses to start at all if the database it connects to
isn't already at the expected revision (`app/core/migration_check.py`) — a second, automatic
line of defense, not a replacement for running the migration step itself.

## Process supervision

Every long-lived process (`backend`, `scheduler`, and all four `worker-*` processes) must be
automatically restarted if it crashes — a system whose entire value proposition is "runs
unattended" cannot tolerate a crashed worker simply staying dead until a human happens to
notice. This repository does not ship a specific supervisor configuration; pick whichever
fits your host:

- **Docker Compose**: `restart: unless-stopped` (or `on-failure`) per service.
- **systemd** (a common choice for a single Linux VPS): one `.service` unit per process, each
  with `Restart=on-failure` and a sane `RestartSec` (a few seconds — avoid a tight crash loop
  hammering Postgres/Redis with reconnect attempts).
- **A process manager** (e.g. supervisord, or a language-agnostic tool you already run other
  services under) — the same requirement, different mechanism.

Whichever you choose, verify it actually restarts a killed process (`kill -9` the PID, confirm
it comes back) before relying on it — this is exactly the kind of thing that looks configured
but isn't, per docs/reviews/PRODUCTION_READINESS_REVIEW.md O5's broader point about unverified
infrastructure.

## Secrets

Injected via the deployment platform's secret store (not committed, not baked into images/
process environments checked into version control) — see `docs/config/CONFIGURATION.md`.
`CREDENTIAL_MASTER_KEY` (the envelope-encryption master key, see `docs/security/SECURITY.md`)
has a documented rotation runbook — exercise it at least once in staging before real plugin
credentials are stored in production. `SENTRY_DSN` (optional — see "Observability" below) is
the one new secret this phase adds; every other required variable is unchanged.

## TLS and public access

Not addressed by this document before docs/reviews/PRODUCTION_READINESS_REVIEW.md O10 flagged
the gap. `uvicorn` does not terminate TLS itself in this deployment — put a reverse proxy
(nginx, Caddy, or your platform's load balancer) in front of it that does, and point
`oauth_callback_base_url`/`oauth_frontend_redirect_url` (`docs/config/CONFIGURATION.md`) at
the real public HTTPS origin once one exists — OAuth providers (Reddit) require an HTTPS
redirect URI in production; `http://localhost:8000` only works for local development. Caddy's
automatic HTTPS (via Let's Encrypt) is the lowest-effort option for a single-host deployment
if you don't already have a preferred reverse proxy.

## Observability in production

See `docs/observability/OBSERVABILITY.md` for the full planned design (OpenTelemetry tracing,
Prometheus/Grafana metrics per plugin and agent) — that stack remains future work, not built.
What's actually implemented today, as of Phase 2D
(docs/reviews/PRODUCTION_HARDENING_REPORT.md):

- Structured JSON logs (`docs/logging/LOGGING.md`) to stdout — pipe to whatever log
  aggregation your host uses.
- **Baseline error tracking**: set `SENTRY_DSN` (or leave it unset — every process behaves
  identically either way) and every process — the FastAPI app and all four `worker-*`
  processes — reports unexpected/5xx-level errors automatically
  (`app/core/observability.py`). This is deliberately narrower than the full OTel/Prometheus
  stack described above: no tracing, no custom metrics, just "don't fail silently in a
  background worker," which was the single worst gap flagged by the readiness review.
- `GET /health` now actually checks Postgres and Redis connectivity (not just "the process is
  up") and returns 503 if either is unreachable
  (docs/reviews/PRODUCTION_READINESS_REVIEW.md O1) — wire your uptime monitor/load balancer
  health check to it.
- **Not yet built**: OpenTelemetry spans, Prometheus metrics, a scheduler heartbeat row.

## Backups

**No backup automation exists in this codebase** — per explicit decision, this phase
documents the procedure rather than scripting it, since the real hosting target (and
therefore the natural place to schedule and store backups) isn't decided yet. The database
holds the encrypted OAuth credential store and the knowledge base described in the original
vision as institutional memory built over months — losing it is not an acceptable failure
mode at any phase. Until automation exists, run this manually (and set a calendar reminder to
run it regularly — a backup procedure nobody executes is not a backup procedure):

```bash
# Full logical backup (portable, human-inspectable, good enough for a single-host deployment
# at this scale — switch to pg_basebackup + WAL archiving if/when point-in-time recovery
# becomes a real requirement).
pg_dump --format=custom --file="growthos-$(date +%Y%m%d-%H%M%S).dump" "$DATABASE_URL"

# Restore into a fresh, empty database:
pg_restore --clean --if-exists --dbname="$DATABASE_URL" growthos-<timestamp>.dump
```

Store the resulting `.dump` file somewhere other than the same disk as the database (off-host
object storage, at minimum) — a backup that lives next to the thing it backs up doesn't
survive the failure mode it exists for. A daily cron/scheduled-task invocation of the
`pg_dump` command above, with retention (e.g. keep the last 14 daily files), is the minimum
viable version of this; automating it (and adding WAL archiving for point-in-time recovery)
remains explicitly tracked as remaining work, not done.

## Path to Kubernetes (if Phase 4 needs it)

Because every process is already a standalone, config-externalized unit
(`docs/config/CONFIGURATION.md`), moving to Kubernetes later is a matter of writing
manifests/Helm charts around the existing code (containerized via the existing
`docker/Dockerfile.*` files, or freshly), not restructuring the application — this is the
actual payoff of keeping processes cleanly separated now rather than a justification to build
Kubernetes manifests today.
