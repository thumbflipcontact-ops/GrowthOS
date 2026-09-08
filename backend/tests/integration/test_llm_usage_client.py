"""Integration tests for LlmUsageClient / llm_usage_logs — see app/services/llm_usage.py and
app/models/llm_usage.py.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.llm.base import CompletionResult
from app.models.agent import AgentConfig, AgentRun, AgentRunStatus
from app.models.identity import Organization
from app.models.llm_usage import LlmUsageLog
from app.models.project import Project
from app.repositories.agent_repository import AgentConfigRepository, AgentRunRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.services.llm_usage import LlmUsageClient

pytestmark = pytest.mark.integration


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-llmusage-{suffix}")
    )
    return await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-llmusage-{suffix}")
    )


@pytest.mark.asyncio
async def test_record_writes_a_row_with_the_computed_cost(db_session) -> None:
    project = await _make_project(db_session)
    client = LlmUsageClient(db_session)

    await client.record(
        org_id=project.org_id,
        project_id=project.id,
        purpose="content_agent.draft_reply",
        result=CompletionResult(
            text="hi", model="claude-sonnet-4-5-20250929", input_tokens=1000, output_tokens=500
        ),
    )

    rows = (
        await db_session.execute(
            select(LlmUsageLog).where(LlmUsageLog.project_id == project.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.org_id == project.org_id
    assert row.purpose == "content_agent.draft_reply"
    assert row.model == "claude-sonnet-4-5-20250929"
    assert row.input_tokens == 1000
    assert row.output_tokens == 500
    assert row.cost_usd > 0
    assert row.agent_run_id is None


@pytest.mark.asyncio
async def test_record_links_the_triggering_agent_run(db_session) -> None:
    project = await _make_project(db_session)
    config = await AgentConfigRepository(db_session).add(
        AgentConfig(project_id=project.id, agent_key="conversation_finder")
    )
    run = await AgentRunRepository(db_session).add(
        AgentRun(
            agent_config_id=config.id,
            project_id=project.id,
            agent_key="conversation_finder",
            status=AgentRunStatus.RUNNING,
        )
    )
    client = LlmUsageClient(db_session)

    await client.record(
        org_id=project.org_id,
        project_id=project.id,
        purpose="conversation_finder.lead_scoring",
        result=CompletionResult(text="x", model="claude-sonnet-4-5", input_tokens=10, output_tokens=10),
        agent_run_id=run.id,
    )

    row = (
        await db_session.execute(select(LlmUsageLog).where(LlmUsageLog.project_id == project.id))
    ).scalar_one()
    assert row.agent_run_id == run.id


@pytest.mark.asyncio
async def test_record_skips_a_result_with_no_token_counts(db_session) -> None:
    # A provider that doesn't report usage (or a test double) must never log as a measured
    # zero-cost call — see LlmUsageClient.record's own docstring.
    project = await _make_project(db_session)
    client = LlmUsageClient(db_session)

    await client.record(
        org_id=project.org_id,
        project_id=project.id,
        purpose="keyword_suggestion",
        result=CompletionResult(text="x", model="claude-sonnet-4-5"),
    )

    rows = (
        await db_session.execute(select(LlmUsageLog).where(LlmUsageLog.project_id == project.id))
    ).scalars().all()
    assert rows == []
