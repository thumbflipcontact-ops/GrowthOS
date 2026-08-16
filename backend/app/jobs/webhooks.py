"""The outbound-webhook Arq worker. See app/core/webhooks/dispatcher.py for the actual sweep
logic — `dispatch_webhooks` here is a thin adapter around `WebhookDispatcher`, the same
separation-of-concerns pattern app/jobs/oauth_refresh.py uses around
app/core/oauth/refresh.py.

Written as a fully standalone module (own WorkerSettings, own queue_name) even though its
cron_jobs entry is what actually gets folded into app/jobs/oauth_refresh.py's existing worker
process for this pass (see that file) — deliberately avoiding the real Railway
service-provisioning friction of a brand-new worker (Custom Build/Start Command setup) for a
feature with near-zero current load. Splitting this into its own Railway service later, if
webhook volume ever justifies it, is a one-line Custom Start Command change
(`cd backend && python -m arq app.jobs.webhooks.WorkerSettings`), not a code change.
"""

from __future__ import annotations

import structlog
from arq import cron

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.migration_check import verify_database_is_migrated
from app.core.observability import init_error_tracking
from app.core.redis import build_redis_settings
from app.core.webhooks.dispatcher import WebhookDispatcher

logger = structlog.get_logger()


async def dispatch_webhooks(ctx: dict) -> int:
    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        dispatcher = WebhookDispatcher(session)
        attempted = await dispatcher.run()
        if attempted:
            logger.info("webhook_dispatcher.cycle_complete", attempted=attempted)
        return attempted


async def startup(ctx: dict) -> None:
    settings = get_settings()
    init_error_tracking(settings, process_name="worker-webhooks")

    engine = create_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    await verify_database_is_migrated(engine)
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    logger.info("worker_webhooks.started")


async def shutdown(ctx: dict) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    queue_name = "webhooks"
    functions = [dispatch_webhooks]
    # Every minute — a delivery's own backoff schedule (30s minimum) is what actually paces
    # retries; this just needs to be frequent enough that a fresh conversation.discovered
    # event doesn't sit around needlessly before its first delivery attempt.
    cron_jobs = [cron(dispatch_webhooks, second=0)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = build_redis_settings(get_settings())
