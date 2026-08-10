"""The scheduler process entrypoint — `python -m app.scheduler`. See
docs/jobs/BACKGROUND_JOBS.md "Scheduling implementation note" and docker-compose.yml's
`scheduler` service.

A lightweight, standalone process (not an Arq worker itself) that polls `agent_configs` on a
fixed interval and enqueues due jobs onto the agent-runs queue — kept separate from any one
worker pool so schedule evaluation doesn't compete with job execution for resources.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime

import structlog
from arq import create_pool

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.logging import configure_logging
from app.core.migration_check import verify_database_is_migrated
from app.core.observability import init_error_tracking
from app.core.redis import build_redis_settings
from app.core.scheduler import Scheduler
from app.models.agent import AgentConfig

logger = structlog.get_logger()

POLL_INTERVAL_SECONDS = 60


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    init_error_tracking(settings, process_name="scheduler")

    engine = create_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    await verify_database_is_migrated(engine)
    session_factory = create_session_factory(engine)
    redis_pool = await create_pool(build_redis_settings(settings))
    scheduler = Scheduler(session_factory)

    async def enqueue(config: AgentConfig) -> None:
        await redis_pool.enqueue_job(
            "run_scheduled_agent", str(config.id), _queue_name="agent_runs"
        )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
    except NotImplementedError:
        # Windows' default ProactorEventLoop doesn't implement add_signal_handler at all
        # (asyncio's docs mark it POSIX-only) — reproduced live running this process
        # standalone on Windows for the first time, not a hypothetical gap. Ctrl+C still
        # raises KeyboardInterrupt there in the normal synchronous way; the try/finally
        # below still runs its cleanup regardless of which platform's mechanism triggered
        # the stop, so behavior converges either way even though the trigger differs.
        pass

    logger.info("scheduler.started", poll_interval_seconds=POLL_INTERVAL_SECONDS)
    try:
        while not stop.is_set():
            now = datetime.now(UTC)
            enqueued = await scheduler.tick(now=now, enqueue=enqueue)
            if enqueued:
                logger.info("scheduler.tick", enqueued=enqueued)
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_SECONDS)
            except TimeoutError:
                pass
    finally:
        await redis_pool.aclose()
        await engine.dispose()
        logger.info("scheduler.stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Windows path (see above) — cleanup already ran in main()'s finally block
