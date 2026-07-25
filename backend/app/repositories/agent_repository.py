from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.agent import AgentConfig, AgentRun
from app.repositories.base import Repository


class AgentConfigRepository(Repository[AgentConfig]):
    model = AgentConfig

    async def list_by_project(self, project_id: uuid.UUID) -> list[AgentConfig]:
        result = await self.session.execute(
            select(AgentConfig).where(AgentConfig.project_id == project_id)
        )
        return list(result.scalars().all())

    async def list_enabled_with_schedule(self) -> list[AgentConfig]:
        """What the scheduler polls — every enabled agent_config with a cron schedule,
        across every project. See app/scheduler.py."""
        result = await self.session.execute(
            select(AgentConfig).where(
                AgentConfig.enabled.is_(True), AgentConfig.schedule_cron.is_not(None)
            )
        )
        return list(result.scalars().all())


class AgentRunRepository(Repository[AgentRun]):
    model = AgentRun

    async def list_by_project(self, project_id: uuid.UUID, *, limit: int = 50) -> list[AgentRun]:
        result = await self.session.execute(
            select(AgentRun)
            .where(AgentRun.project_id == project_id)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
