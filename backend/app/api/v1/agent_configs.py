"""Agent config + on-demand trigger + run-history endpoints. See docs/api/API_DESIGN.md and
docs/agents/AGENT_ARCHITECTURE.md. No agent-specific code here or ever should be — `agent_key`
is validated dynamically via app/core/agent_registry.load_agent, the same generic pattern
app/api/v1/plugin_connections.py uses for `plugin_key` against the plugin catalog.
"""

from __future__ import annotations

from arq import ArqRedis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_arq_redis, get_current_user, get_db, require_project_access
from app.core.agent_registry import load_agent
from app.models.agent import AgentConfig, AgentRun
from app.models.audit import AuditLog
from app.models.identity import User
from app.models.project import Project
from app.repositories.agent_repository import AgentConfigRepository, AgentRunRepository
from app.schemas.agent import (
    AgentConfigResponse,
    AgentConfigUpsertRequest,
    AgentRunResponse,
    AgentTriggerResponse,
)
from app.services.agent_config import AgentConfigService

router = APIRouter(prefix="/projects/{project_id}/agent-configs", tags=["agent-configs"])


@router.get("", response_model=list[AgentConfigResponse])
async def list_agent_configs(
    project: Project = Depends(require_project_access),
    session: AsyncSession = Depends(get_db),
) -> list[AgentConfig]:
    return await AgentConfigRepository(session).list_by_project(project.id)


@router.put("/{agent_key}", response_model=AgentConfigResponse)
async def upsert_agent_config(
    agent_key: str,
    body: AgentConfigUpsertRequest,
    project: Project = Depends(require_project_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AgentConfig:
    """Create-or-update — matches `agent_configs`' `unique(project_id, agent_key)` constraint,
    so this is safe to call repeatedly (e.g. re-saving a settings form)."""
    return await AgentConfigService(session).upsert(
        project_id=project.id,
        org_id=project.org_id,
        actor_user_id=current_user.id,
        agent_key=agent_key,
        config=body.config,
        schedule_cron=body.schedule_cron,
        enabled=body.enabled,
    )


@router.post("/{agent_key}/runs/trigger", response_model=AgentTriggerResponse, status_code=202)
async def trigger_agent_run(
    agent_key: str,
    project: Project = Depends(require_project_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_redis),
) -> AgentTriggerResponse:
    """On-demand run — enqueues the exact same `run_scheduled_agent` job the cron scheduler
    enqueues (app/scheduler.py), so there is one job body, one code path, for both triggers.
    Auto-provisions a disabled-schedule `agent_configs` row on first trigger if none exists
    yet, so a project doesn't need a separate "enable this agent" step before its first
    on-demand run — see docs/api/API_DESIGN.md."""
    load_agent(agent_key)  # 404s for an unknown agent_key before anything else happens

    configs = AgentConfigRepository(session)
    config = await configs.get_by_project_and_key(project.id, agent_key)
    if config is None:
        config = await configs.add(AgentConfig(project_id=project.id, agent_key=agent_key))

    await arq_redis.enqueue_job("run_scheduled_agent", str(config.id))

    session.add(
        AuditLog(
            org_id=project.org_id,
            actor_user_id=current_user.id,
            action="agent_config.run_triggered",
            target=agent_key,
        )
    )

    return AgentTriggerResponse(agent_config_id=config.id, agent_key=agent_key)


@router.get("/{agent_key}/runs", response_model=list[AgentRunResponse])
async def list_agent_runs(
    agent_key: str,
    project: Project = Depends(require_project_access),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AgentRun]:
    return await AgentRunRepository(session).list_by_project_and_key(
        project.id, agent_key, limit=limit
    )
