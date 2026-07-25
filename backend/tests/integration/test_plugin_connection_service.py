"""Service-level coverage of PluginConnectionService's validation logic, isolated from HTTP —
see backend/tests/integration/test_plugin_connections_api.py for the end-to-end version.
Uses a real db_session (repository writes need a real Postgres transaction), so this lives
alongside the other integration tests rather than tests/unit."""

from __future__ import annotations

import uuid

import pytest
from plugins._shared.manifest import PluginManifest
from pydantic import BaseModel

from app.core.errors import NotFoundError, ValidationError
from app.core.plugin_catalog import PluginCatalog
from app.models.identity import Organization, User
from app.models.project import Project
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.services.plugin_connection import PluginConnectionService

pytestmark = pytest.mark.integration


class _Config(BaseModel):
    greeting: str = "hello"


def _catalog() -> PluginCatalog:
    catalog = PluginCatalog()
    catalog.refresh(
        [
            PluginManifest(
                key="dummy",
                interface_version="1.0",
                capabilities=("searchable",),
                config_schema=_Config,
            )
        ]
    )
    return catalog


@pytest.mark.asyncio
async def test_create_rejects_unknown_plugin_key(db_session) -> None:
    service = PluginConnectionService(db_session, _catalog())
    with pytest.raises(NotFoundError):
        await service.create(
            project_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            plugin_key="nope",
            config={},
            capabilities_enabled=[],
        )


@pytest.mark.asyncio
async def test_create_rejects_invalid_config(db_session) -> None:
    service = PluginConnectionService(db_session, _catalog())
    with pytest.raises(ValidationError):
        await service.create(
            project_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            plugin_key="dummy",
            config={"greeting": 123},
            capabilities_enabled=[],
        )


@pytest.mark.asyncio
async def test_create_rejects_undeclared_capability(db_session) -> None:
    service = PluginConnectionService(db_session, _catalog())
    with pytest.raises(ValidationError):
        await service.create(
            project_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            plugin_key="dummy",
            config={},
            capabilities_enabled=["publishable"],
        )


@pytest.mark.asyncio
async def test_create_succeeds_with_valid_input(db_session) -> None:
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug="acme-plugin-conn-service")
    )
    project = await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug="scoutseo-plugin-conn-service")
    )
    user = await UserRepository(db_session).add(
        User(email="owner@example.com", name="Owner", password_hash="x")
    )

    service = PluginConnectionService(db_session, _catalog())
    connection = await service.create(
        project_id=project.id,
        org_id=org.id,
        actor_user_id=user.id,
        plugin_key="dummy",
        config={"greeting": "hi"},
        capabilities_enabled=["searchable"],
    )
    assert connection.plugin_key == "dummy"
    assert connection.config == {"greeting": "hi"}


@pytest.mark.asyncio
async def test_create_writes_an_audit_log_row(db_session) -> None:
    """See docs/auth/AUTHENTICATION.md §"Plugin credentials vs. user authentication":
    "Connecting, disconnecting, or reconfiguring a plugin connection writes an audit_log
    row." """
    from sqlalchemy import select

    from app.models.audit import AuditLog

    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug="acme-plugin-conn-audit")
    )
    project = await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug="scoutseo-plugin-conn-audit")
    )
    user = await UserRepository(db_session).add(
        User(email="audit-owner@example.com", name="Owner", password_hash="x")
    )

    service = PluginConnectionService(db_session, _catalog())
    await service.create(
        project_id=project.id,
        org_id=org.id,
        actor_user_id=user.id,
        plugin_key="dummy",
        config={},
        capabilities_enabled=[],
    )

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "plugin_connection.created")
    )
    audit_row = result.scalar_one()
    assert audit_row.org_id == org.id
    assert audit_row.actor_user_id == user.id
    assert audit_row.target == "dummy"
