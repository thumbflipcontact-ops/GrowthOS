"""The agent-lifecycle cost-control Arq worker. See app/core/agent_lifecycle.py for the actual
sweep logic — `sweep_agent_lifecycle` here is a thin adapter around
`AgentLifecycleSweep`, the same separation-of-concerns pattern app/jobs/oauth_refresh.py uses
around app/core/oauth/refresh.py.
"""

from __future__ import annotations

import structlog
from arq import cron

from app.core.agent_lifecycle import AgentLifecycleSweep
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.migration_check import verify_database_is_migrated
from app.core.observability import init_error_tracking
from app.core.redis import build_redis_settings

logger = structlog.get_logger()


async def sweep_agent_lifecycle(ctx: dict) -> int:
    settings = get_settings()
    session_factory = ctx["session_factory"]

    async with session_factory() as session:
        sweep = AgentLifecycleSweep(session, settings)
        disabled = await sweep.run()
        if disabled:
            logger.info("agent_lifecycle.cycle_complete", disabled=disabled)
        return disabled


async def startup(ctx: dict) -> None:
    settings = get_settings()
    init_error_tracking(settings, process_name="worker-agent-lifecycle")

    engine = create_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    await verify_database_is_migrated(engine)
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    logger.info("worker_agent_lifecycle.started")


async def shutdown(ctx: dict) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    queue_name = "agent_lifecycle"
    functions = [sweep_agent_lifecycle]
    # Hourly — these are date-granularity conditions (48h inactivity, a 7-day trial boundary),
    # not the tight-deadline case oauth_refresh has; being caught up to ~1 hour late costs at
    # most ~1 extra hour of a few metered API calls for the affected org, immaterial next to
    # the cost this job guards against. Consistent with app/services/agent_config.py's own
    # 6-hour minimum-interval philosophy for conversation_finder-adjacent cost logic.
    cron_jobs = [cron(sweep_agent_lifecycle, minute=0)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = build_redis_settings(get_settings())
