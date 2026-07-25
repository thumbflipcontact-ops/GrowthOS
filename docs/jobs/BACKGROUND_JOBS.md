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
   trigger for a publish attempt (`ARCHITECTURE.md` §8).
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

- Agent runs: retried up to 3 times with exponential backoff on transient failures (network
  errors, rate-limit responses from a plugin). An agent run must be safe to retry from
  scratch — this is why `knowledge_items` has `unique(project_id, url)`: a retried
  `conversation_finder` run re-encountering a thread it already partially processed upserts
  rather than duplicates.
- Publish jobs: retried up to 3 times, then the `content_item` stays `approved` with
  `publish_error` populated and surfaces in the dashboard for manual retry — never silently
  dropped, and never auto-transitioned to any other status by a failure (a failed publish is
  not a rejection; a human should decide what happens next).
- All jobs carry a deterministic idempotency key (e.g. `content_item.id` for publish jobs) so
  a duplicate enqueue (e.g. from an API retry with the same `Idempotency-Key`, see
  `docs/api/API_DESIGN.md`) is a no-op if the job already ran successfully.
- Event dispatch: each subscriber handler job is keyed by `(domain_event.id, subscriber_key)`,
  so a dispatcher retry (or a crash mid-cycle before `dispatched_at` is set) re-enqueues
  without double-triggering a subscriber that already ran successfully for that event.

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
