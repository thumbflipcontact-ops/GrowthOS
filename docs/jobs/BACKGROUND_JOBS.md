# Background Job Architecture

**Version 2** — adds the event dispatch job category and queue, the mechanism agents use to
react to each other's output. See `ARCHITECTURE.md` §7 and
`docs/decisions/0006-event-driven-agent-communication.md`.

## Why Arq over Celery

See `docs/decisions/0002-task-queue.md` for the full reasoning. Summary: GrowthOS's workload
is I/O-bound (LLM calls, external API calls), async-native FastAPI is already the framework,
and Arq is a thin, Redis-native async job queue with a fraction of Celery's operational
surface (no separate result backend to choose, no Flower dependency for basic visibility, no
task-routing configuration to get wrong). Celery's strengths — complex workflow DAGs, mature
ecosystem of exotic broker/backend combinations — aren't needed here. Arq now also serves as
the event-dispatch mechanism (below), reinforcing rather than complicating this choice — see
`docs/decisions/0006-event-driven-agent-communication.md`.

## Job categories

1. **Scheduled agent runs.** Cron-like schedules per `agent_configs.schedule_cron`, enqueued
   by a lightweight scheduler process that reads `agent_configs` and enqueues Arq jobs — not
   Arq's own cron decorator directly, because schedules are per-project runtime config
   (database rows), not static code. Reserved for agents that originate a cycle rather than
   react to one (e.g. `conversation_finder`) — see `docs/agents/AGENT_ARCHITECTURE.md`.
2. **Event dispatch.** A periodic Arq job (short interval, tunable — see
   `docs/architecture/LOCKED_DECISIONS.md` §2) that reads undispatched rows from
   `domain_events` and enqueues one Arq job per subscribed handler, then marks
   `dispatched_at`. This is how an agent's `EventSubscription` actually gets invoked — see
   `ARCHITECTURE.md` §7. Undispatched rows surviving a dispatcher crash are simply picked up
   on the next cycle; nothing is lost.
3. **On-demand agent runs.** Enqueued directly by the API when a user clicks "re-run now."
4. **Publish jobs.** Enqueued when a `content_item` transitions to `approved` — the only
   trigger for a publish attempt (`ARCHITECTURE.md` §8). **Implemented in Phase 2C** —
   `app/jobs/publish.py`'s `publish_content_item`, enqueued by
   `app/api/v1/content_items.py`'s `approve` endpoint (and re-enqueueable via
   `retry-publish` for a previously-exhausted-retries item) — see
   `docs/reviews/PUBLISHING_WORKFLOW_IMPLEMENTATION_REPORT.md`.
5. **Enrichment/maintenance jobs.** Knowledge Base Agent's periodic enrichment pass, plugin
   `health_check()` polling, `plugin_catalog` refresh on startup, and — implemented alongside
   the OAuth2 framework (`docs/auth/OAUTH2_ARCHITECTURE.md`) — `app/jobs/oauth_refresh.py`,
   a periodic sweep that refreshes any `connected` OAuth token nearing expiry. Locks
   candidate rows (`FOR UPDATE SKIP LOCKED`) so a concurrent sweep run or a user-triggered
   reconnect never double-processes the same connection. A permanent failure
   (`invalid_grant`) transitions the connection to `expired`; a transient failure (network,
   provider 5xx) leaves it `connected` for the next cycle to retry.

## Queues

Separate Arq queues for **agent runs**, **event dispatch**, and **publish jobs** — so a
backlog of scheduled research work never delays a time-sensitive publish job sitting in
`approved` waiting to go out, a burst of approvals never starves the next morning's scheduled
runs, and a slow agent-run backlog never delays event dispatch (which is the latency-
sensitive path for webhook-triggered reactivity — see `docs/plugins/PLUGIN_ARCHITECTURE.md`
§Webhooks). Each queue has its own worker pool size, tuned independently (see
`docs/scalability/SCALABILITY.md`).

## Retries & idempotency

**Implemented for real as of Phase 2D** (docs/reviews/PRODUCTION_HARDENING_REPORT.md) — every
claim below is now verified against the code, not just the design intent. Previously, every
job re-raised a plain exception on failure intending Arq's `max_tries` to retry it; Arq only
retries a job that raises its own `arq.worker.Retry`, so none of this ever actually happened
— see docs/reviews/PRODUCTION_READINESS_REVIEW.md §3.1 for the full finding. `app/core/
job_retry.py` is the one place the correct exception type and the shared backoff formula live.

- Agent runs: retried up to 3 times with exponential backoff (`retry_backoff_seconds`, capped
  at 60s) on transient failures (network errors, rate-limit responses from a plugin). An
  agent run must be safe to retry from scratch — this is why `knowledge_items` has
  `unique(project_id, url)`: a retried `conversation_finder` run re-encountering a thread it
  already partially processed upserts rather than duplicates.
- Publish jobs: retried up to 3 times, then the `content_item` stays `approved` with
  `publish_error` populated and surfaces via the API for manual retry
  (`POST .../content-items/{id}/retry-publish`) — never silently dropped, and never
  auto-transitioned to any other status by a failure (a failed publish is not a rejection; a
  human should decide what happens next). Every attempt — success or failure, whether
  triggered by approval, an Arq retry, or a manual retry — is recorded as its own
  `content_publish_attempts` row, independent of the single current-state `publish_error`
  column. Before ever calling a plugin, the job also checks for a prior *successful* attempt
  already recorded (closing docs/reviews/PRODUCTION_READINESS_REVIEW.md R2 — a crash between
  a plugin call succeeding and that success being committed could otherwise cause a duplicate
  post on the next attempt); finding one reconciles the item to `published` instead of
  posting again.
- Publish jobs and event-dispatch jobs (below) carry a deterministic idempotency key so a
  duplicate enqueue is a no-op while the original is queued/running. **Not yet true of every
  job**: the on-demand agent-trigger endpoint (`POST .../agent-configs/{agent_key}/runs/
  trigger`) and the scheduler's own periodic enqueue (`app/scheduler.py`) do not pass a
  `_job_id` yet — a network retry or double-click there can enqueue two independent agent
  runs. Tracked as remaining work (docs/reviews/PRODUCTION_READINESS_REVIEW.md R3), not fixed
  in Phase 2D (medium severity, scoped out in favor of the higher-severity findings).
- Event dispatch: each subscriber handler job is keyed by `event.id` + `agent_key`
  (`app/jobs/events.py`'s `_event_job_id`), so a dispatcher crash-and-redispatch re-enqueues
  without double-triggering a subscriber job still queued/running for that event. The
  dispatcher itself also now commits `dispatched_at` per event rather than once for the whole
  batch (`app/core/dispatcher.py`), narrowing a crash's blast radius to the one event that was
  mid-flight instead of silently re-processing everything already handled in that cycle — see
  docs/reviews/PRODUCTION_READINESS_REVIEW.md R1.

## Observability

Every job logs start/end/status through the shared structured logging setup
(`docs/logging/LOGGING.md`) tagged with `project_id`, `agent_key`/`job_type`, and a job id —
this is what `agent_runs` rows are ultimately sourced from. Arq's built-in job result storage
in Redis is treated as transient (short TTL); `agent_runs` in Postgres is the durable record.

## Scheduling implementation note

The scheduler process (reads `agent_configs`, enqueues due jobs) runs as its own lightweight
container/process, polling on a short interval (e.g. every minute) rather than each project
running its own OS-level cron — this keeps schedule changes (a user edits
`agent_configs.schedule_cron` in the dashboard) effective immediately, with no deploy or
container restart required.
