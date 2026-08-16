from __future__ import annotations

import uuid

from sqlalchemy import func, select

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

    async def list_enabled_by_key(self, agent_key: str) -> list[AgentConfig]:
        """What app/core/agent_lifecycle.py's cost-control sweep polls — every enabled
        agent_config for a given agent_key, across every project, regardless of whether it has
        a schedule (unlike list_enabled_with_schedule above)."""
        result = await self.session.execute(
            select(AgentConfig).where(
                AgentConfig.enabled.is_(True), AgentConfig.agent_key == agent_key
            )
        )
        return list(result.scalars().all())

    async def get_by_project_and_key(
        self, project_id: uuid.UUID, agent_key: str
    ) -> AgentConfig | None:
        """Matches `agent_configs`' `unique(project_id, agent_key)` constraint — the lookup
        both the on-demand trigger endpoint and AgentConfigService's upsert use."""
        result = await self.session.execute(
            select(AgentConfig).where(
                AgentConfig.project_id == project_id, AgentConfig.agent_key == agent_key
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, project_id: uuid.UUID, agent_key: str) -> AgentConfig:
        """Auto-provisions a default (disabled schedule, empty config, enabled) row the
        first time something needs one for this (project, agent_key) pair — used by the
        on-demand trigger endpoint and by the event-triggered job runner
        (app/jobs/events.py), since `agent_runs.agent_config_id` is a required FK and a
        subscription-only agent (e.g. content_agent) has no schedule to have already
        created one via a scheduling UI."""
        existing = await self.get_by_project_and_key(project_id, agent_key)
        if existing is not None:
            return existing
        return await self.add(AgentConfig(project_id=project_id, agent_key=agent_key))


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

    async def list_by_project_and_key(
        self, project_id: uuid.UUID, agent_key: str, *, limit: int = 50, offset: int = 0
    ) -> list[AgentRun]:
        """The run history behind `GET .../agent-configs/{agent_key}/runs` — see
        docs/api/API_DESIGN.md. Backed by idx_agent_runs_project_key_created (migration
        d3e5f7a9b2c4) so this WHERE + ORDER BY + LIMIT/OFFSET stays an index scan rather than
        a sequential scan as a project's run history grows."""
        result = await self.session.execute(
            select(AgentRun)
            .where(AgentRun.project_id == project_id, AgentRun.agent_key == agent_key)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_project_and_key(self, project_id: uuid.UUID, agent_key: str) -> int:
        """Total row count for the same (project_id, agent_key) predicate
        list_by_project_and_key filters on — lets the frontend compute total pages without
        fetching every row. Same index as above serves this count."""
        result = await self.session.execute(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.project_id == project_id, AgentRun.agent_key == agent_key)
        )
        return result.scalar_one()
