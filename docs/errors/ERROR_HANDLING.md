# Error Handling Strategy

## Exception hierarchy

A small set of domain exceptions, defined once in `backend/app/core/errors.py`, that every
layer raises instead of generic `Exception` or bare HTTP errors:

```python
class GrowthOSError(Exception):
    """Base for all domain errors."""

class NotFoundError(GrowthOSError): ...
class ValidationError(GrowthOSError): ...
class CapabilityNotSupported(GrowthOSError):
    """Raised when the registry is asked for a plugin capability it doesn't structurally
    implement (see docs/plugins/PLUGIN_ARCHITECTURE.md's segmented Protocols) or that the
    project hasn't enabled at the connection level. mypy already prevents most of this at
    the type-check stage for in-repo callers; this exception is the runtime backstop for
    dynamically-resolved lookups (e.g. by plugin_key from request data). Must never be
    silently caught and swallowed anywhere in agent or service code."""
class InvalidStateTransition(GrowthOSError):
    """Raised by ContentApprovalService on an illegal content_item status transition, or on
    a version mismatch from the concurrency guard — see ARCHITECTURE.md §8."""
class PluginError(GrowthOSError):
    """Wraps any failure from an external system call, with the originating plugin_key."""
class RateLimited(PluginError): ...
```

A single FastAPI exception handler maps each of these to a consistent HTTP response; nothing
in a route handler writes ad hoc `HTTPException(status_code=..., detail=...)` for a case
already covered by a domain exception.

## API error envelope

```json
{
  "error": {
    "code": "invalid_state_transition",
    "message": "Content item is not pending_review (current status: approved)",
    "details": {}
  }
}
```

`code` is a stable, machine-readable snake_case identifier (one per domain exception type,
occasionally more granular) — the frontend branches on `code`, never on `message` text,
since `message` is allowed to change for clarity without being a breaking change.

## Two failure philosophies, applied deliberately by context

- **Fail loud** for anything that touches the approval/publish state machine, credential
  handling, or a violated invariant (e.g. `CapabilityNotSupported`,
  `InvalidStateTransition`). These are bugs or misconfigurations, not expected operational
  variance — they should be impossible to accidentally catch-and-continue past, propagate
  as exceptions, and show up as `ERROR`-level logs and (in production) alerting.
- **Fail soft, per-source** for agent runs querying multiple plugins — one plugin timing out
  or rate-limiting should not fail the entire `agent_run`. `conversation_finder` querying
  five plugins where one raises `PluginError` logs a `WARNING`, records the partial failure
  in `agent_runs.summary`, and continues with the other four. The run itself is marked
  `succeeded` with a noted partial failure, not `failed` — a fully failed run should mean
  the agent itself couldn't do its job, not that one of several sources was unavailable.

## Retries

Transient failures (network timeouts, `RateLimited`) are retried with exponential backoff at
the job level (see `docs/jobs/BACKGROUND_JOBS.md`), not scattered as ad hoc `try/except`
retry loops inside agent or plugin code — retry policy is a job-execution concern, defined
once.

## User-facing errors (frontend)

Domain error `code`s map to specific, actionable UI messages (e.g.
`invalid_state_transition` → "This item was already reviewed — refresh to see its current
status," not a generic "Something went wrong"). Unmapped/unexpected errors fall back to a
generic message plus the `request_id`, so a real bug report can be traced to its log line.

## What we do not do

- No bare `except: pass` anywhere — caught in code review, not just convention.
- No swallowing `CapabilityNotSupported` — a plugin capability mismatch is a configuration
  bug that should surface, not degrade silently into "nothing happened."
- No generic 500s in place of a specific domain error where one exists — a 500 should mean
  "genuinely unexpected," always paired with a full traceback in the error tracker (see
  `docs/observability/OBSERVABILITY.md` and `docs/deployment/DEPLOYMENT.md`).
