"""The agent-runs Arq worker. See docs/jobs/BACKGROUND_JOBS.md.

`run_scheduled_agent`'s body is a placeholder in Phase 1 — invoking a real agent's `run()`
against a real `AgentContext` is business logic explicitly out of scope (see ROADMAP.md: no
Conversation Finder, no Content Agent, no agent business logic). This exists so the queue
plumbing (scheduler enqueues → worker picks up → retries on failure, per
docs/jobs/BACKGROUND_JOBS.md's retry policy) is real and tested; Phase 2 replaces the body
with real agent dispatch through agents/_shared.base.Agent.
"""

from __future__ import annotations

import structlog
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory

logger = structlog.get_logger()


async def run_scheduled_agent(ctx: dict, agent_config_id: str) -> None:
    logger.info("agent_run.placeholder", agent_config_id=agent_config_id)


async def startup(ctx: dict) -> None:
    settings = get_settings()
    engine = create_engine(str(settings.database_url))
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)


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
