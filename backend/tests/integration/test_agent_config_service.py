"""Integration tests for AgentConfigService — see app/services/agent_config.py and
docs/api/API_DESIGN.md. Uses the real `conversation_finder` agent package (pip installed
editable) so config_schema validation runs against a real pydantic model, not a mock — same
precedent as test_plugin_connections_api.py using the real `dummy` plugin.
"""

from __future__ import annotations

import uuid

import pytest
from app.core.errors import NotFoundError, ValidationError
from app.models.audit import AuditLog
from app.models.identity import Organization, User
from app.models.project import Project
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.services.agent_config import AgentConfigService

pytestmark = pytest.mark.integration


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-ac-{suffix}")
    )
    project = await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-ac-{suffix}")
    )
    return project


async def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:8]
    return await UserRepository(db_session).add(
        User(email=f"u-{suffix}@example.com", name="U", password_hash="x")
    )


@pytest.mark.asyncio
async def test_upsert_creates_a_new_config_and_writes_an_audit_row(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    service = AgentConfigService(db_session)

    config = await service.upsert(
        project_id=project.id,
        org_id=project.org_id,
        actor_user_id=user.id,
        agent_key="conversation_finder",
        config={"keywords": ["crawl budget"]},
        schedule_cron="0 6 * * *",
        enabled=True,
    )

    assert config.agent_key == "conversation_finder"
    assert config.config == {"keywords": ["crawl budget"]}
    assert config.schedule_cron == "0 6 * * *"

    from sqlalchemy import select

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "agent_config.created")
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_upsert_updates_the_same_row_on_a_second_call(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    service = AgentConfigService(db_session)

    first = await service.upsert(
        project_id=project.id,
        org_id=project.org_id,
        actor_user_id=user.id,
        agent_key="conversation_finder",
        config={"keywords": ["crawl budget"]},
        schedule_cron=None,
        enabled=True,
    )
    second = await service.upsert(
        project_id=project.id,
        org_id=project.org_id,
        actor_user_id=user.id,
        agent_key="conversation_finder",
        config={"keywords": ["canonical tags"]},
        schedule_cron="0 6 * * *",
        enabled=False,
    )

    assert second.id == first.id
    assert second.config == {"keywords": ["canonical tags"]}
    assert second.enabled is False


@pytest.mark.asyncio
async def test_upsert_rejects_config_that_fails_the_agents_own_schema(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    service = AgentConfigService(db_session)

    with pytest.raises(ValidationError):
        await service.upsert(
            project_id=project.id,
            org_id=project.org_id,
            actor_user_id=user.id,
            agent_key="conversation_finder",
            config={"min_score_to_save": "not-a-number"},
            schedule_cron=None,
            enabled=True,
        )


@pytest.mark.asyncio
async def test_upsert_rejects_an_unknown_agent_key(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    service = AgentConfigService(db_session)

    with pytest.raises(NotFoundError):
        await service.upsert(
            project_id=project.id,
            org_id=project.org_id,
            actor_user_id=user.id,
            agent_key="not-a-real-agent",
            config={},
            schedule_cron=None,
            enabled=True,
        )
