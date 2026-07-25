"""The scheduler's core tick logic. See docs/jobs/BACKGROUND_JOBS.md "Scheduling
implementation note".

Separated from app/scheduler.py's process entrypoint the same way app/core/dispatcher.py is
separated from app/jobs/events.py: `Scheduler.tick()` takes an injected `enqueue` callback,
so the actual "is this cron schedule due" logic is unit-testable without a running Arq
worker or a real Redis connection.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from croniter import croniter
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.agent import AgentConfig
from app.repositories.agent_repository import AgentConfigRepository

EnqueueFn = Callable[[AgentConfig], Awaitable[None]]


def is_due(cron_expression: str, since: datetime, now: datetime) -> bool:
    """True if `cron_expression` has a fire time in (since, now] — i.e. a schedule that
    would have fired at least once since the scheduler's last poll. Using an open-lower,
    closed-upper interval means a fire time exactly at `since` (already handled last tick)
    is not re-triggered, and one exactly at `now` is not missed until next tick."""
    next_fire: datetime = croniter(cron_expression, since).get_next(datetime)
    return bool(since < next_fire <= now)


class Scheduler:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory
        self._last_tick: datetime | None = None

    async def tick(self, *, now: datetime, enqueue: EnqueueFn) -> int:
        """Reads every enabled, schedule-bearing agent_config across every project and
        enqueues the ones due since the last tick. Returns the count enqueued. The caller
        (app/scheduler.py) is responsible for calling this on a fixed interval — see
        `docs/jobs/BACKGROUND_JOBS.md`."""
        # On the very first tick after process start, `since` is `now` — an empty window,
        # so nothing fires until the second tick. This is deliberate: it avoids a burst of
        # every "overdue while the scheduler was down" job firing at once on restart. A
        # schedule due right at startup fires on the next tick, one poll interval later —
        # an acceptable trade-off for a system whose schedules are day-granularity cron
        # expressions, not sub-minute ones.
        since = self._last_tick if self._last_tick is not None else now
        enqueued = 0
        async with self.session_factory() as session:
            configs = await AgentConfigRepository(session).list_enabled_with_schedule()
            for config in configs:
                assert config.schedule_cron is not None  # guaranteed by the query filter
                if is_due(config.schedule_cron, since, now):
                    await enqueue(config)
                    enqueued += 1
        self._last_tick = now
        return enqueued
