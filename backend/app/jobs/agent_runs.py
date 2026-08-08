"""The agent-runs Arq worker. See docs/jobs/BACKGROUND_JOBS.md.

Phase 2A wires this up for real: `run_scheduled_agent` loads the `agent_configs` row, builds
a concrete `AgentContext` (a `PluginRegistry` scoped to the project's connections, the
concrete `KnowledgeBaseClient`, the transactional `EventPublisher`), invokes the agent's
`run()`, and records the outcome as an `agent_runs` row — the durable, per-attempt audit
trail docs/jobs/BACKGROUND_JOBS.md's "Observability" section describes. A failure records the
row, then raises `arq.worker.Retry` so Arq's own retry policy (`max_tries = 3` below) actually
applies (see docs/reviews/PRODUCTION_READINESS_REVIEW.md §3.1 and app/core/job_retry.py — a
plain re-raise here never retried at all, regardless of `max_tries`) — each attempt gets its
own `agent_runs` row, which is the intended behavior: every attempt genuinely happened and the
row is the record of it.

Wired for schedule-triggered agents (`conversation_finder`) — app/jobs/events.py's
subscription-triggered `run_agent_for_event` is the equivalent job body for subscription-
triggered agents (`content_agent`, Phase 2B), built alongside it against the identical
AgentContext-construction pattern.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from agents._shared.base import AgentContext
from arq.connections import RedisSettings
from arq.worker import Retry

from app.core.agent_registry import load_agent
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.entitlements import is_org_entitled
from app.core.events import EventPublisher
from app.core.job_retry import retry_backoff_seconds
from app.core.llm.base import LLMProvider
from app.core.llm.factory import build_llm_provider
from app.core.migration_check import verify_database_is_migrated
from app.core.observability import capture_exception, capture_operator_alert, init_error_tracking
from app.core.plugin_catalog import PluginCatalog, discover_installed_plugins
from app.core.plugin_registry import PluginRegistry
from app.models.agent import AgentConfig, AgentRun, AgentRunStatus
from app.models.project import Project
from app.repositories.plugin_repository import PluginConnectionRepository
from app.services.content_drafts import ContentDraftClient
from app.services.knowledge_base import KnowledgeBaseClient

logger = structlog.get_logger()


async def run_scheduled_agent(ctx: dict, agent_config_id: str) -> None:
    session_factory = ctx["session_factory"]
    settings = ctx["settings"]
    catalog: PluginCatalog = ctx["plugin_catalog"]
    llm: LLMProvider = ctx["llm_provider"]

    async with session_factory() as session:
        config = await session.get(AgentConfig, uuid.UUID(agent_config_id))
        if config is None:
            logger.warning("agent_run.config_missing", agent_config_id=agent_config_id)
            return
        # No `config.enabled` check here on purpose, even though this same job body also
        # serves the cron scheduler (app/scheduler.py): the scheduler only ever enqueues
        # for configs it already queried as enabled in the first place
        # (AgentConfigRepository.list_enabled_with_schedule) — this would be pure redundant
        # defense-in-depth for that path. But this job also serves the on-demand trigger
        # endpoint (app/api/v1/agent_configs.py's trigger_agent_run), where a check here has
        # the opposite effect: a human explicitly clicking "Run now" would silently no-op —
        # no error, no AgentRun row, nothing — for any project that had ever unchecked "Run
        # automatically." An explicit manual trigger should always run.

        project = await session.get(Project, config.project_id)
        if project is None:
            logger.error("agent_run.project_missing", agent_config_id=agent_config_id)
            return

        # Cost-safety gate, not just an HTTP-layer concern (app/api/deps.py's
        # require_active_subscription): a scheduled agent has no HTTP request to reject, so
        # this is the only place a canceled/expired org's *cron-triggered* runs actually stop
        # spending its own metered plugin API calls and LLM tokens. See
        # docs/billing/BILLING_ARCHITECTURE.md.
        if not await is_org_entitled(session, project.org_id):
            logger.info(
                "agent_run.skipped_org_not_entitled",
                agent_config_id=agent_config_id,
                org_id=str(project.org_id),
            )
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
                llm=llm,
                knowledge_base=KnowledgeBaseClient(session),
                content=ContentDraftClient(session),
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
            capture_exception(exc)
            raise Retry(defer=retry_backoff_seconds(ctx.get("job_try", 1))) from exc

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

        # A "succeeded" run can still carry operator_alerts (see agents/_shared/base.py) —
        # a plugin failure that's the platform's problem, not this customer's, and never
        # raises (so the except block above never sees it). These are the one thing in this
        # function still worth paging a human for even though the run itself is fine.
        for alert in result.operator_alerts:
            run_logger.error("agent_run.operator_alert", alert=alert)
            capture_operator_alert(
                alert, agent_key=config.agent_key, project_id=str(config.project_id)
            )


async def startup(ctx: dict) -> None:
    settings = get_settings()
    init_error_tracking(settings, process_name="worker-agent-runs")

    engine = create_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    await verify_database_is_migrated(engine)
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    ctx["settings"] = settings

    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    ctx["plugin_catalog"] = catalog

    # Built once per worker process, not per job — the underlying HTTP client is meant to be
    # reused, the same reasoning app/core/db.py's engine is built once at startup rather than
    # per request/job.
    ctx["llm_provider"] = build_llm_provider(settings)
    logger.info("worker_agent_runs.started", plugins=[m.key for m in catalog.all()])


async def shutdown(ctx: dict) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    # Every worker in this deployment shares one Redis instance — without a distinct
    # queue_name here, arq's default queue is shared across all 4 worker processes, so any
    # of them can pop a job meant for another (e.g. worker-oauth-refresh popping
    # run_scheduled_agent and failing with "function not found", since only this worker's
    # functions list includes it). Every enqueue_job call targeting this worker must pass
    # the matching _queue_name="agent_runs" — see app/scheduler.py and
    # app/api/v1/agent_configs.py.
    queue_name = "agent_runs"
    functions = [run_scheduled_agent]
    on_startup = startup
    on_shutdown = shutdown
    # Retries with exponential backoff on transient failure — see
    # docs/jobs/BACKGROUND_JOBS.md "Retries & idempotency". Arq's default backoff is
    # exponential; max_tries mirrors the documented "retried up to 3 times."
    max_tries = 3
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
