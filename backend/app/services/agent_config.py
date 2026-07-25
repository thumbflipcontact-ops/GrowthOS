"""Create/update a project's `agent_configs` row. See docs/api/API_DESIGN.md and
docs/agents/AGENT_ARCHITECTURE.md.

Mirrors app/services/plugin_connection.py's shape: validate the submitted `config` against
the target agent's own `config_schema` — resolved dynamically via
app/core/agent_registry.load_agent, exactly like a plugin connection's config is validated
against `PluginCatalog.get(plugin_key).config_schema` — before writing anything. No
agent-specific code here or ever should be; a second agent (content_agent, Phase 2B) needs no
changes to this file.
"""

from __future__ import annotations

import uuid

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_registry import load_agent
from app.core.errors import ValidationError
from app.models.agent import AgentConfig
from app.models.audit import AuditLog
from app.repositories.agent_repository import AgentConfigRepository


class AgentConfigService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.configs = AgentConfigRepository(session)

    async def upsert(
        self,
        *,
        project_id: uuid.UUID,
        org_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        agent_key: str,
        config: dict,
        schedule_cron: str | None,
        enabled: bool,
    ) -> AgentConfig:
        agent = load_agent(agent_key)  # raises NotFoundError (404) for an unknown agent_key
        try:
            agent.config_schema.model_validate(config)
        except PydanticValidationError as exc:
            raise ValidationError(
                f"Config does not match agent {agent_key!r}'s config_schema.",
                details={"agent_key": agent_key, "errors": exc.errors()},
            ) from exc

        existing = await self.configs.get_by_project_and_key(project_id, agent_key)
        is_update = existing is not None
        record = existing or AgentConfig(project_id=project_id, agent_key=agent_key)
        record.config = config
        record.schedule_cron = schedule_cron
        record.enabled = enabled
        if not is_update:
            self.session.add(record)
        await self.session.flush()

        # See CONTRIBUTING.md's plugin-connection precedent (app/services/plugin_connection.py):
        # any project-scoped config a human writes through the API gets an audit_log row.
        self.session.add(
            AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action="agent_config.updated" if is_update else "agent_config.created",
                target=agent_key,
            )
        )
        await self.session.flush()
        return record

    async def list_for_project(self, project_id: uuid.UUID) -> list[AgentConfig]:
        return await self.configs.list_by_project(project_id)
