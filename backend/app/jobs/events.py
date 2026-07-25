"""The event-dispatch Arq worker. See docs/jobs/BACKGROUND_JOBS.md "Event dispatch" and
ARCHITECTURE.md §7. Runs as its own worker pool (`worker-events` in
docker/docker-compose.yml) so a backlog of agent-run work never delays dispatch latency.

`dispatch_domain_events` is the periodic job; `run_agent_for_event` is the per-subscriber
job it enqueues. Its body is a placeholder in Phase 1 — invoking a real agent's `run()` is
business logic explicitly out of scope (see ROADMAP.md); this exists so the queue plumbing
(cron trigger → dispatch → per-subscriber enqueue → job execution) is real and tested end to
end, not just the dispatch-logic half of it.
"""

from __future__ import annotations

import structlog
from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.dispatcher import EventDispatcher
from app.core.subscriptions import SubscriptionRegistry, discover_agent_subscriptions
from app.models.event import DomainEvent

logger = structlog.get_logger()


async def dispatch_domain_events(ctx: dict) -> int:
    session_factory = ctx["session_factory"]
    registry: SubscriptionRegistry = ctx["subscription_registry"]

    async with session_factory() as session:
        dispatcher = EventDispatcher(session, registry)

        async def enqueue(agent_key: str, event: DomainEvent) -> None:
            await ctx["redis"].enqueue_job("run_agent_for_event", agent_key, str(event.id))

        processed = await dispatcher.dispatch_pending(enqueue)
        if processed:
            logger.info("event_dispatch.cycle_complete", events_processed=processed)
        return processed


async def run_agent_for_event(ctx: dict, agent_key: str, event_id: str) -> None:
    logger.info("agent_run.placeholder", agent_key=agent_key, event_id=event_id)


async def startup(ctx: dict) -> None:
    settings = get_settings()
    engine = create_engine(str(settings.database_url))
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)

    registry = SubscriptionRegistry()
    registry.refresh(discover_agent_subscriptions())
    ctx["subscription_registry"] = registry
    logger.info("worker_events.started", subscribed_agents=[s.agent_key for s in registry.all()])


async def shutdown(ctx: dict) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [dispatch_domain_events, run_agent_for_event]
    # Every 5 seconds — tunable, deliberately left flexible per
    # docs/architecture/LOCKED_DECISIONS.md §2 ("Event dispatcher poll interval").
    cron_jobs = [cron(dispatch_domain_events, second=set(range(0, 60, 5)))]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
