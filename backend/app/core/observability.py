"""Optional error-tracking integration — see docs/reviews/PRODUCTION_READINESS_REVIEW.md
O8/O9 and docs/reviews/PRODUCTION_HARDENING_REPORT.md.

Deliberately minimal and fully optional: if `SENTRY_DSN` isn't set, every function here is a
no-op and nothing about existing behavior changes. This is NOT the full OpenTelemetry +
Prometheus/Grafana stack docs/observability/OBSERVABILITY.md describes — that remains a
separate, larger, future workstream (see that doc's own note). This closes the narrower, more
urgent gap: an agent run or a publish attempt failing silently in a background worker, visible
only in a local stdout log line, is the single worst failure mode for a system whose entire
value proposition is "runs unattended" — so *some* automatic, off-box error visibility is a
requirement before real usage, even before the full observability stack exists.
"""

from __future__ import annotations

import structlog

from app.core.config import Settings

logger = structlog.get_logger()

_enabled = False


def init_error_tracking(settings: Settings, *, process_name: str) -> None:
    """Idempotent per-process Sentry init — safe to call from every process's startup
    (main.py's lifespan, each Arq worker's startup(), scheduler.py's main()). No-ops if
    SENTRY_DSN isn't configured."""
    global _enabled
    if _enabled or not settings.sentry_dsn:
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        server_name=process_name,
        # Error tracking only — no APM/tracing spend by default. Full tracing belongs to the
        # OpenTelemetry workstream in docs/observability/OBSERVABILITY.md, not this module.
        traces_sample_rate=0.0,
    )
    _enabled = True
    logger.info("observability.sentry_initialized", process_name=process_name)


def capture_exception(exc: BaseException) -> None:
    """No-op if Sentry isn't initialized. Every call site already logs via structlog
    regardless of whether this does anything, so this is additive visibility, never the only
    record of a failure."""
    if not _enabled:
        return

    import sentry_sdk

    sentry_sdk.capture_exception(exc)
