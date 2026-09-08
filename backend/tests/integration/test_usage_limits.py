"""Integration tests for the monthly agent-run cap — see app/core/usage_limits.py. DB-backed
(counts real `agent_runs` rows), so these live alongside the other DB-dependent gate tests
(test_billing_entitlements.py) rather than in tests/unit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.usage_limits import MAX_AGENT_RUNS_PER_MONTH, has_reached_run_cap, runs_this_month
from app.models.agent import AgentConfig, AgentRun, AgentRunStatus
from app.models.identity import Organization
from app.models.project import Project
from app.repositories.agent_repository import AgentConfigRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository

pytestmark = pytest.mark.integration


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-usage-{suffix}")
    )
    return await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-usage-{suffix}")
    )


async def _get_or_create_config(db_session, project, agent_key: str) -> AgentConfig:
    # agent_configs has a unique (project_id, agent_key) constraint — reused across every
    # AgentRun this helper creates for the same project+agent_key, rather than re-inserting
    # one per call.
    existing = await AgentConfigRepository(db_session).get_by_project_and_key(
        project.id, agent_key
    )
    if existing is not None:
        return existing
    return await AgentConfigRepository(db_session).add(
        AgentConfig(project_id=project.id, agent_key=agent_key)
    )


async def _add_run(db_session, project, *, agent_key: str = "conversation_finder", created_at=None):
    config = await _get_or_create_config(db_session, project, agent_key)
    run = AgentRun(
        agent_config_id=config.id,
        project_id=project.id,
        agent_key=agent_key,
        status=AgentRunStatus.SUCCEEDED,
    )
    db_session.add(run)
    await db_session.flush()
    if created_at is not None:
        run.created_at = created_at
        await db_session.flush()
    return run


@pytest.mark.asyncio
async def test_runs_this_month_counts_runs_from_the_current_calendar_month_only(db_session) -> None:
    project = await _make_project(db_session)
    await _add_run(db_session, project)
    await _add_run(db_session, project)
    last_month = datetime.now(UTC).replace(day=1) - timedelta(days=1)
    await _add_run(db_session, project, created_at=last_month)

    assert await runs_this_month(db_session, project.id) == 2


@pytest.mark.asyncio
async def test_runs_this_month_is_scoped_per_project(db_session) -> None:
    project_a = await _make_project(db_session)
    project_b = await _make_project(db_session)
    await _add_run(db_session, project_a)
    await _add_run(db_session, project_a)
    await _add_run(db_session, project_b)

    assert await runs_this_month(db_session, project_a.id) == 2
    assert await runs_this_month(db_session, project_b.id) == 1


@pytest.mark.asyncio
async def test_runs_this_month_counts_across_every_agent_key(db_session) -> None:
    """Deliberately agent-agnostic (see usage_limits.py's docstring) — a conversation_finder
    run and a content_agent run both count toward the same shared cap."""
    project = await _make_project(db_session)
    await _add_run(db_session, project, agent_key="conversation_finder")
    await _add_run(db_session, project, agent_key="content_agent")

    assert await runs_this_month(db_session, project.id) == 2


@pytest.mark.asyncio
async def test_has_reached_run_cap_is_false_below_the_cap_and_true_at_it(db_session) -> None:
    project = await _make_project(db_session)
    for _ in range(MAX_AGENT_RUNS_PER_MONTH - 1):
        await _add_run(db_session, project)
    assert await has_reached_run_cap(db_session, project.id) is False

    await _add_run(db_session, project)
    assert await has_reached_run_cap(db_session, project.id) is True
