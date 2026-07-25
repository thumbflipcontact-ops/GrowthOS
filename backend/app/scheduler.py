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
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.logging import configure_logging
from app.core.scheduler import Scheduler
from app.models.agent import AgentConfig

logger = structlog.get_logger()

POLL_INTERVAL_SECONDS = 60


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)

    engine = create_engine(str(settings.database_url))
    session_factory = create_session_factory(engine)
    redis_pool = await create_pool(RedisSettings.from_dsn(str(settings.redis_url)))
    scheduler = Scheduler(session_factory)

    async def enqueue(config: AgentConfig) -> None:
        await redis_pool.enqueue_job("run_scheduled_agent", str(config.id))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

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
    asyncio.run(main())
