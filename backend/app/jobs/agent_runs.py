"""The agent-runs Arq worker. See docs/jobs/BACKGROUND_JOBS.md.

Phase 2A wires this up for real: `run_scheduled_agent` loads the `agent_configs` row, builds
a concrete `AgentContext` (a `PluginRegistry` scoped to the project's connections, the
concrete `KnowledgeBaseClient`, the transactional `EventPublisher`), invokes the agent's
`run()`, and records the outcome as an `agent_runs` row — the durable, per-attempt audit
trail docs/jobs/BACKGROUND_JOBS.md's "Observability" section describes. A failure re-raises
after recording the row, so Arq's own retry policy (`max_tries = 3` below) still applies —
each attempt gets its own `agent_runs` row, which is the intended behavior: every attempt
genuinely happened and the row is the record of it.

Only wired for schedule-triggered agents so far (`conversation_finder`) —
app/jobs/events.py's subscription-triggered `run_agent_for_event` stays a placeholder until a
subscribing agent (`content_agent`, Phase 2B) exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from agents._shared.base import AgentContext
from arq.connections import RedisSettings

from app.core.agent_registry import load_agent
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.events import EventPublisher
from app.core.plugin_catalog import PluginCatalog, discover_installed_plugins
from app.core.plugin_registry import PluginRegistry
from app.models.agent import AgentConfig, AgentRun, AgentRunStatus
from app.models.project import Project
from app.repositories.plugin_repository import PluginConnectionRepository
from app.services.knowledge_base import KnowledgeBaseClient

logger = structlog.get_logger()


async def run_scheduled_agent(ctx: dict, agent_config_id: str) -> None:
    session_factory = ctx["session_factory"]
    settings = ctx["settings"]
    catalog: PluginCatalog = ctx["plugin_catalog"]

    async with session_factory() as session:
        config = await session.get(AgentConfig, uuid.UUID(agent_config_id))
        if config is None or not config.enabled:
            logger.warning("agent_run.config_missing_or_disabled", agent_config_id=agent_config_id)
            return

        project = await session.get(Project, config.project_id)
        if project is None:
            logger.error("agent_run.project_missing", agent_config_id=agent_config_id)
            return

        run = AgentRun(
            agent_config_id=config.id,
            project_id=config.project_id,
            agent_key=config.agent_key,
            status=AgentRunStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()

        run_logger = logger.bind(
            agent_key=config.agent_key,
            project_id=str(config.project_id),
            agent_run_id=str(run.id),
        )

        try:
            agent = load_agent(config.agent_key)
            connections = await PluginConnectionRepository(session).list_by_project(
                config.project_id
            )
            agent_ctx = AgentContext(
                project=project,
                config=config.config,
                plugins=PluginRegistry(catalog, connections, settings),
                llm=None,
                knowledge_base=KnowledgeBaseClient(session),
                events=EventPublisher(session),
                logger=run_logger,
                agent_run_id=run.id,
            )
            result = await agent.run(agent_ctx)
        except Exception as exc:
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(UTC)
            run.error = str(exc)
            await session.commit()
            run_logger.error("agent_run.failed", exc_info=True)
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
            "agent_run.succeeded", knowledge_items_created=result.knowledge_items_created
        )


async def startup(ctx: dict) -> None:
    settings = get_settings()
    engine = create_engine(str(settings.database_url))
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    ctx["settings"] = settings

    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    ctx["plugin_catalog"] = catalog
    logger.info("worker_agent_runs.started", plugins=[m.key for m in catalog.all()])


async def shutdown(ctx: dict) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [run_scheduled_agent]
    on_startup = startup
    on_shutdown = shutdown
    # Retries with exponential backoff on transient failure — see
    # docs/jobs/BACKGROUND_JOBS.md "Retries & idempotency". Arq's default backoff is
    # exponential; max_tries mirrors the documented "retried up to 3 times."
    max_tries = 3
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
