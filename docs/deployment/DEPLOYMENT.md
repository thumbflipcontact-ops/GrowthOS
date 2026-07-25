# Deployment Strategy

## v1 target: single-host Docker Compose

A single VPS (or equivalent) running Docker Compose is the right deployment shape for a
single-operator system with a handful of background workers and moderate traffic — not
Kubernetes. See `docs/decisions/` for the reasoning if this is ever revisited; the short
version is that Kubernetes' operational overhead buys nothing until there's a real multi-
tenant scaling requirement (Phase 4, see `ROADMAP.md`), and premature infrastructure
complexity is a cost paid every day, not just once.

## Services

```
docker/docker-compose.yml
├── backend        FastAPI app (uvicorn/gunicorn) — also hosts the plugin_catalog manifest
│                    scan at startup, see docs/plugins/PLUGIN_ARCHITECTURE.md
├── frontend        Next.js app
├── worker-agents    Arq worker, agent-runs queue
├── worker-events    Arq worker, event-dispatch queue AND the periodic dispatcher job itself
│                    (docs/jobs/BACKGROUND_JOBS.md) — kept separate from worker-agents so a
│                    backlog of agent runs never delays event dispatch latency
├── worker-publish   Arq worker, publish-jobs queue (separate pool — see docs/jobs/BACKGROUND_JOBS.md)
├── scheduler        Polls agent_configs, enqueues due schedule-triggered jobs
├── postgres          Postgres + pgvector (system of record, incl. domain_events outbox)
└── redis              Arq broker (job execution + event dispatch), cache, rate limiting
```

No new *kind* of service versus the original design — `worker-events` is another Arq worker
process, identical in shape to `worker-agents`/`worker-publish`, just pointed at a different
queue. This is the concrete payoff of choosing Arq/Postgres-outbox over a dedicated message
broker (`ARCHITECTURE.md` §7): event dispatch fits the existing deployment topology instead
of requiring a new category of infrastructure.

Each service is its own Dockerfile under `docker/`, all built from the same base Python
image where applicable (`backend`, `worker-*`, `scheduler` share a base layer) to keep image
build times and registry storage reasonable.

## Environments

| Environment | Purpose | Notes |
|---|---|---|
| Local | Development | `docker compose up`, hot-reload on backend and frontend |
| Staging | Pre-production validation | Same compose file, separate `.env`, separate database — used to validate a new agent/plugin against real (but non-production-critical) external calls before it touches the live ScoutSEO project |
| Production | Live | Same images as staging, promoted after staging validation, not rebuilt from source at deploy time |

## CI/CD

1. PR opened → lint + unit/contract/integration tests (`docs/testing/TESTING.md`).
2. Merge to `main` → build images, tag with commit SHA, run end-to-end suite against the
   built images in a CI-only compose stack.
3. Manual promotion (a deliberate step, not automatic) deploys the tagged image to staging,
   then production — this system controls real, external-facing publishing actions, so an
   accidental bad deploy has a higher blast radius than a typical internal tool; the
   promotion step stays manual until there's enough deployment history to trust automating
   it.

## Migrations

Alembic migrations run as a one-off job/step before the new `backend` image starts serving
traffic, not as an app-startup side effect — a migration failure should block the deploy
loudly, not degrade into the app half-starting.

## Secrets

Injected via the deployment platform's secret store (not committed, not baked into images) —
see `docs/config/CONFIGURATION.md`. `CREDENTIAL_MASTER_KEY` (the envelope-encryption master
key, see `docs/security/SECURITY.md`) has a documented rotation runbook — exercise it at
least once in staging before real plugin credentials are stored in production.

## Observability in production

See `docs/observability/OBSERVABILITY.md` for the full design (OpenTelemetry tracing,
Prometheus/Grafana metrics per plugin and agent). Summary of what runs where:

- Structured JSON logs (`docs/logging/LOGGING.md`) shipped to the host's log aggregation.
- Error tracking (e.g. Sentry) wired into the FastAPI app and every Arq worker (`worker-agents`,
  `worker-events`, `worker-publish`) — an agent run or event dispatch failing silently in a
  background worker is the single worst failure mode for a system whose entire value is
  "runs unattended every morning," so worker error visibility is a production-readiness
  requirement, not a nice-to-have.
- Metrics: OpenTelemetry spans on every plugin capability call and agent run, exported to
  Prometheus, with the `domain_events` dispatch lag (age of the oldest undispatched row) as
  the key health signal for the event architecture specifically.
- Basic uptime/health checks per service (`/health` on the API; a lightweight heartbeat row
  the scheduler writes on each poll cycle, alertable if it goes stale).

## Backups

Postgres: automated daily snapshots plus WAL archiving for point-in-time recovery — this
database holds the knowledge base described in the original vision as institutional memory
built over months; losing it is not an acceptable failure mode at any phase.

## Path to Kubernetes (if Phase 4 needs it)

Because every service is already a standalone Dockerfile with externalized config
(`docs/config/CONFIGURATION.md`), moving to Kubernetes later is a matter of writing
manifests/Helm charts around the existing images, not restructuring the application — this
is the actual payoff of keeping services cleanly separated in Compose now rather than a
justification to build Kubernetes manifests today.
