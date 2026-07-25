"""The event-dispatch Arq worker. See docs/jobs/BACKGROUND_JOBS.md "Event dispatch" and
ARCHITECTURE.md §7. Runs as its own worker pool (`worker-events` in
docker/docker-compose.yml) so a backlog of agent-run work never delays dispatch latency.

`dispatch_domain_events` is the periodic job; `run_agent_for_event` is the per-subscriber
job it enqueues — the subscription-triggered counterpart to app/jobs/agent_runs.py's
schedule-triggered `run_scheduled_agent`, built against the identical AgentContext-
construction pattern once a subscription-only agent (`content_agent`, Phase 2B) existed to
need it. It auto-provisions an `agent_configs` row the same way the on-demand trigger
endpoint does (see AgentConfigRepository.get_or_create) — a subscription-only agent has no
schedule to have already created one via a scheduling UI, but `agent_runs.agent_config_id` is
a required FK regardless of trigger kind.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from agents._shared.base import AgentContext
from arq import cron
from arq.connections import RedisSettings

from app.core.agent_registry import load_agent
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.dispatcher import EventDispatcher
from app.core.events import EventPublisher
from app.core.llm.base import LLMProvider
from app.core.llm.factory import build_llm_provider
from app.core.plugin_catalog import PluginCatalog, discover_installed_plugins
from app.core.plugin_registry import PluginRegistry
from app.core.subscriptions import SubscriptionRegistry, discover_agent_subscriptions
from app.models.agent import AgentRun, AgentRunStatus
from app.models.event import DomainEvent
from app.models.project import Project
from app.repositories.agent_repository import AgentConfigRepository
from app.repositories.plugin_repository import PluginConnectionRepository
from app.services.content_drafts import ContentDraftClient
from app.services.knowledge_base import KnowledgeBaseClient

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
    session_factory = ctx["session_factory"]
    settings = ctx["settings"]
    catalog: PluginCatalog = ctx["plugin_catalog"]
    llm: LLMProvider = ctx["llm_provider"]

    async with session_factory() as session:
        event = await session.get(DomainEvent, uuid.UUID(event_id))
        if event is None:
            logger.warning("agent_run_for_event.event_missing", event_id=event_id)
            return

        project = await session.get(Project, event.project_id)
        if project is None:
            logger.error("agent_run_for_event.project_missing", event_id=event_id)
            return

        config = await AgentConfigRepository(session).get_or_create(event.project_id, agent_key)
        if not config.enabled:
            logger.info(
                "agent_run_for_event.agent_disabled_for_project",
                agent_key=agent_key,
                project_id=str(event.project_id),
            )
            return

        run = AgentRun(
            agent_config_id=config.id,
            project_id=event.project_id,
            agent_key=agent_key,
            status=AgentRunStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()

        run_logger = logger.bind(
            agent_key=agent_key,
            project_id=str(event.project_id),
            agent_run_id=str(run.id),
            event_id=event_id,
        )

        try:
            agent = load_agent(agent_key)
            connections = await PluginConnectionRepository(session).list_by_project(
                event.project_id
            )
            agent_ctx = AgentContext(
                project=project,
                config=config.config,
                plugins=PluginRegistry(catalog, connections, settings),
                llm=llm,
                knowledge_base=KnowledgeBaseClient(session),
                content=ContentDraftClient(session),
                events=EventPublisher(session),
                logger=run_logger,
                agent_run_id=run.id,
                trigger_payload=event.payload,
            )
            result = await agent.run(agent_ctx)
        except Exception as exc:
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(UTC)
            run.error = str(exc)
            await session.commit()
            run_logger.error("agent_run_for_event.failed", exc_info=True)
            raise  # let Arq's retry policy (WorkerSettings.max_tries) apply

        run.status = AgentRunStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.summary = {
            "knowledge_items_created": result.knowledge_items_created,
            "content_items_created": result.content_items_created,
            "errors": result.errors,
            "details": result.summary,
        }
        await session.commit()
        run_logger.info(
            "agent_run_for_event.succeeded", content_items_created=result.content_items_created
        )


async def startup(ctx: dict) -> None:
    settings = get_settings()
    engine = create_engine(str(settings.database_url))
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    ctx["settings"] = settings

    registry = SubscriptionRegistry()
    registry.refresh(discover_agent_subscriptions())
    ctx["subscription_registry"] = registry

    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    ctx["plugin_catalog"] = catalog

    ctx["llm_provider"] = build_llm_provider(settings)
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
    # Retries with exponential backoff on transient failure, same policy as
    # app/jobs/agent_runs.py — see docs/jobs/BACKGROUND_JOBS.md "Retries & idempotency".
    max_tries = 3
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
