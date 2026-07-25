# Logging Strategy

This document covers what to log and how. For metrics, tracing, and dashboards — the
complementary "what's happening in aggregate" view logs alone don't answer well, especially
across a 100+ plugin surface — see `docs/observability/OBSERVABILITY.md`.

## Structured, always

All logging goes through `structlog`, emitting JSON in staging/production and
human-readable colorized output locally (same log calls, different renderer based on
`ENVIRONMENT`). No bare `print()` and no unstructured string-interpolated log messages
anywhere in the codebase — a log line that can't be queried by field is a log line that
won't get looked at when it matters.

## Required context on every log line

A shared logging middleware/context-binder ensures every log line emitted during a request
or a job carries, when applicable:

- `request_id` (API requests) or `job_id` (background jobs)
- `org_id`, `project_id` — every operation in GrowthOS is project-scoped; a log line without
  this context is nearly useless for debugging a specific project's behavior
- `agent_key` / `plugin_key` — when the log originates from agent or plugin code
- `user_id` — when the operation was triggered by an authenticated user action

```python
logger = structlog.get_logger()
logger.bind(project_id=project.id, agent_key="conversation_finder", job_id=job_id)
logger.info("agent_run.completed", knowledge_items_created=4, duration_ms=8421)
```

## What never gets logged

- Plugin credentials, decrypted or encrypted, in full — log the `plugin_key` and connection
  `id`, never the credential value itself, even at DEBUG level.
- Full LLM prompts/completions at INFO level in production (they may contain the founder's
  business-sensitive ICP/brand data and third parties' content) — available at DEBUG level
  only, and DEBUG is never enabled in production.
- Anything typed `SecretStr` via the `Settings` model (see `docs/config/CONFIGURATION.md`) —
  structlog's processor chain includes a redaction step that stringifies `SecretStr` fields
  as `**********` even if a log call accidentally includes the settings object.

## Log levels

| Level | Use |
|---|---|
| `DEBUG` | Full LLM prompts/completions, raw plugin API responses — local/staging only |
| `INFO` | Agent run start/complete, content item state transitions, publish attempts |
| `WARNING` | Plugin rate-limited/degraded, agent run completed with partial failures |
| `ERROR` | Agent run failed, publish failed after retries, unhandled exception |

## Where logs go

Local: stdout, human-readable. Staging/production: stdout as JSON, collected by the
deployment platform's log aggregation (see `docs/deployment/DEPLOYMENT.md`) — GrowthOS itself
does not manage log storage or retention; that's infrastructure, not application concern.

## Audit trail vs. logs — don't conflate them

Logs are for debugging and operational visibility and can be sampled, rotated, or lost
without consequence. The actual audit trail of what GrowthOS did — every `agent_run`, every
`content_item` state transition with `reviewed_by_user_id`/`reviewed_at`, every publish
attempt — lives in Postgres as described in `docs/database/SCHEMA.md`, precisely because that
data must never be lost the way logs are allowed to be.
