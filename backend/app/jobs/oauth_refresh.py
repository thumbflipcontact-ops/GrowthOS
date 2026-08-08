"""The OAuth token-refresh Arq worker. See docs/jobs/BACKGROUND_JOBS.md ("credential-refresh
jobs for OAuth tokens nearing expiry", listed there as an enrichment/maintenance job category
since Phase 1) and docs/auth/OAUTH2_ARCHITECTURE.md §5.2, §7.

`refresh_oauth_tokens` is the periodic job — a thin adapter around
`app.core.oauth.refresh.OAuthRefreshSweep`, the same separation-of-concerns pattern
app/jobs/events.py already uses around app/core/dispatcher.py.
"""

from __future__ import annotations

import structlog
from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.migration_check import verify_database_is_migrated
from app.core.oauth.refresh import OAuthRefreshSweep
from app.core.observability import init_error_tracking
from app.core.plugin_catalog import PluginCatalog, discover_installed_plugins

logger = structlog.get_logger()


async def refresh_oauth_tokens(ctx: dict) -> int:
    settings = get_settings()
    session_factory = ctx["session_factory"]
    catalog: PluginCatalog = ctx["plugin_catalog"]

    async with session_factory() as session:
        sweep = OAuthRefreshSweep(session, catalog, settings)
        processed = await sweep.run()
        if processed:
            logger.info("oauth_refresh.cycle_complete", connections_processed=processed)
        return processed


async def startup(ctx: dict) -> None:
    settings = get_settings()
    init_error_tracking(settings, process_name="worker-oauth-refresh")

    engine = create_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    await verify_database_is_migrated(engine)
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)

    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    ctx["plugin_catalog"] = catalog
    logger.info("worker_oauth_refresh.started", plugins=[m.key for m in catalog.all()])


async def shutdown(ctx: dict) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    # See app/jobs/agent_runs.py's queue_name docstring. Nothing outside this file enqueues
    # onto it (refresh_oauth_tokens only ever runs via its own cron_jobs entry below), but
    # the name is still set for consistency and to keep this worker isolated if that changes.
    queue_name = "oauth_refresh"
    functions = [refresh_oauth_tokens]
    # Every 5 minutes — comfortably inside REFRESH_WINDOW's 10-minute margin (a token first
    # becomes a refresh candidate at T-10m, so it's caught within one cycle, well before
    # actual expiry). Tunable, same flexibility note as the event dispatcher's poll interval —
    # see docs/architecture/LOCKED_DECISIONS.md §2.
    cron_jobs = [cron(refresh_oauth_tokens, minute=set(range(0, 60, 5)))]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
