"""Integration tests for KnowledgeBaseClient / KnowledgeItemRepository — see
docs/knowledge-base/KNOWLEDGE_BASE.md and app/services/knowledge_base.py.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from app.models.identity import Organization
from app.models.project import Project
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.services.knowledge_base import KnowledgeBaseClient

pytestmark = pytest.mark.integration


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-kb-{suffix}")
    )
    return await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-kb-{suffix}")
    )


@pytest.mark.asyncio
async def test_upsert_discovery_creates_a_new_row(db_session) -> None:
    project = await _make_project(db_session)
    client = KnowledgeBaseClient(db_session)

    item, created = await client.upsert_discovery(
        project_id=project.id,
        platform="reddit",
        url="https://reddit.com/r/SEO/1",
        tags=["crawl budget"],
        confidence=Decimal("0.80"),
    )

    assert created is True
    assert item.id is not None
    assert item.platform == "reddit"
    assert item.tags == ["crawl budget"]
    assert item.buying_intent.value == "none"  # Phase 2A never sets this — see README.md
    assert item.problem is None


@pytest.mark.asyncio
async def test_upsert_discovery_refreshes_an_existing_row_by_url_instead_of_duplicating(
    db_session,
) -> None:
    project = await _make_project(db_session)
    client = KnowledgeBaseClient(db_session)

    first, first_created = await client.upsert_discovery(
        project_id=project.id,
        platform="reddit",
        url="https://reddit.com/r/SEO/2",
        tags=["crawl budget"],
        confidence=Decimal("0.40"),
    )
    second, second_created = await client.upsert_discovery(
        project_id=project.id,
        platform="reddit",
        url="https://reddit.com/r/SEO/2",
        tags=["crawl budget", "canonical tags"],
        confidence=Decimal("0.90"),
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id  # same row, not a duplicate
    assert second.tags == ["crawl budget", "canonical tags"]
    assert second.confidence == Decimal("0.90")


@pytest.mark.asyncio
async def test_upsert_discovery_is_scoped_per_project(db_session) -> None:
    project_a = await _make_project(db_session)
    project_b = await _make_project(db_session)
    client = KnowledgeBaseClient(db_session)

    same_url = "https://reddit.com/r/SEO/shared"
    _, a_created = await client.upsert_discovery(
        project_id=project_a.id, platform="reddit", url=same_url, tags=[], confidence=Decimal("0.5")
    )
    _, b_created = await client.upsert_discovery(
        project_id=project_b.id, platform="reddit", url=same_url, tags=[], confidence=Decimal("0.5")
    )

    assert a_created is True
    assert b_created is True  # a different project's dedup key — not the same row


@pytest.mark.asyncio
async def test_get_by_url_returns_none_when_not_found(db_session) -> None:
    project = await _make_project(db_session)
    client = KnowledgeBaseClient(db_session)

    assert await client.get_by_url(project.id, "https://reddit.com/nope") is None
