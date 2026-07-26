"""Integration tests for ContentDraftClient / ContentItemRepository — see
docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md and app/services/content_drafts.py.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.agent import AgentConfig, AgentRun, AgentRunStatus
from app.models.audit import AuditLog
from app.models.content import ContentItemStatus
from app.models.identity import Organization
from app.models.project import Project
from app.repositories.agent_repository import AgentConfigRepository, AgentRunRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.services.content_drafts import ContentDraftClient
from app.services.knowledge_base import KnowledgeBaseClient

pytestmark = pytest.mark.integration


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-cd-{suffix}")
    )
    return await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-cd-{suffix}")
    )


@pytest.mark.asyncio
async def test_create_draft_writes_a_draft_status_row_with_every_field(db_session) -> None:
    project = await _make_project(db_session)
    client = ContentDraftClient(db_session)

    knowledge_item, _ = await KnowledgeBaseClient(db_session).upsert_discovery(
        project_id=project.id,
        platform="reddit",
        url="https://reddit.com/r/SEO/1",
        tags=[],
        confidence=Decimal("0.5"),
    )
    config = await AgentConfigRepository(db_session).add(
        AgentConfig(project_id=project.id, agent_key="content_agent")
    )
    agent_run = await AgentRunRepository(db_session).add(
        AgentRun(
            agent_config_id=config.id,
            project_id=project.id,
            agent_key="content_agent",
            status=AgentRunStatus.RUNNING,
        )
    )

    item = await client.create_draft(
        project_id=project.id,
        type="reddit_reply",
        body="Here's a helpful reply.",
        confidence=Decimal("0.75"),
        reasoning="Because the post asked about crawl budget.",
        evidence=["Google isn't indexing all our pages."],
        target_platform="reddit",
        target_ref="t3_abc123",
        knowledge_item_id=knowledge_item.id,
        source_agent_run_id=agent_run.id,
    )

    assert item.id is not None
    assert item.status.value == "draft"
    assert item.type == "reddit_reply"
    assert item.body == "Here's a helpful reply."
    assert item.confidence == Decimal("0.75")
    assert item.reasoning == "Because the post asked about crawl budget."
    assert item.evidence == ["Google isn't indexing all our pages."]
    assert item.target_platform == "reddit"
    assert item.target_ref == "t3_abc123"
    assert item.knowledge_item_id == knowledge_item.id
    assert item.created_by_agent_run_id == agent_run.id
    assert item.reviewed_by_user_id is None
    assert item.reviewed_at is None
    assert item.published_at is None
    assert item.version == 1


@pytest.mark.asyncio
async def test_create_draft_defaults_reasoning_and_evidence(db_session) -> None:
    project = await _make_project(db_session)
    client = ContentDraftClient(db_session)

    item = await client.create_draft(
        project_id=project.id,
        type="reddit_reply",
        body="hi",
        confidence=Decimal("0.5"),
    )

    assert item.reasoning is None
    assert item.evidence == []
    assert item.target_platform is None
    assert item.target_ref is None
    assert item.knowledge_item_id is None
    assert item.created_by_agent_run_id is None


@pytest.mark.asyncio
async def test_submit_for_review_advances_a_passing_draft_and_writes_an_audit_row(
    db_session,
) -> None:
    project = await _make_project(db_session)
    client = ContentDraftClient(db_session)
    item = await client.create_draft(
        project_id=project.id, type="reddit_reply", body="A short, clean reply.",
        confidence=Decimal("0.75"),
    )

    check = await client.submit_for_review(item, org_id=project.org_id, max_length=1000)

    assert check.passed is True
    assert check.reasons == []
    assert item.status == ContentItemStatus.PENDING_REVIEW
    # Not a human review — this is a system auto-advance, per ARCHITECTURE.md §8.
    assert item.reviewed_by_user_id is None
    assert item.reviewed_at is None

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "content_item.submitted_for_review")
        )
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.target == str(item.id)
    assert audit.actor_user_id is None


@pytest.mark.asyncio
async def test_submit_for_review_leaves_a_failing_draft_in_draft_with_no_audit_row(
    db_session,
) -> None:
    project = await _make_project(db_session)
    client = ContentDraftClient(db_session)
    item = await client.create_draft(
        project_id=project.id, type="reddit_reply", body="x" * 200, confidence=Decimal("0.75")
    )

    check = await client.submit_for_review(item, org_id=project.org_id, max_length=100)

    assert check.passed is False
    assert any("max_length" in reason for reason in check.reasons)
    assert item.status == ContentItemStatus.DRAFT

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "content_item.submitted_for_review")
        )
    ).scalar_one_or_none()
    assert audit is None


@pytest.mark.asyncio
async def test_submit_for_review_checks_banned_phrases(db_session) -> None:
    project = await _make_project(db_session)
    client = ContentDraftClient(db_session)
    item = await client.create_draft(
        project_id=project.id,
        type="reddit_reply",
        body="Buy now, guaranteed results!",
        confidence=Decimal("0.75"),
    )

    check = await client.submit_for_review(
        item, org_id=project.org_id, max_length=1000, banned_phrases=["guaranteed results"]
    )

    assert check.passed is False
    assert item.status == ContentItemStatus.DRAFT
