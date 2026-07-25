"""End-to-end tests for the content-items read API — see docs/api/API_DESIGN.md and
app/api/v1/content_items.py.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from app.services.content_drafts import ContentDraftClient
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def api_client(db_session, _migrated_db):
    from app.api.deps import get_db
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def project_id(api_client: AsyncClient, db_session) -> str:
    from app.repositories.organization_repository import OrganizationRepository

    await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-content-items",
            "email": "ciowner@example.com",
            "name": "Owner",
            "password": "correct-horse-battery-staple",
        },
    )
    org = await OrganizationRepository(db_session).get_by_slug("acme-content-items")
    assert org is not None

    create = await api_client.post(
        f"/api/v1/orgs/{org.id}/projects",
        json={"name": "ScoutSEO", "slug": "scoutseo-content-items"},
    )
    assert create.status_code == 201
    return create.json()["id"]


@pytest.mark.asyncio
async def test_list_content_items_returns_drafts(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    client = ContentDraftClient(db_session)
    await client.create_draft(
        project_id=uuid.UUID(project_id),
        type="reddit_reply",
        body="A helpful reply.",
        confidence=Decimal("0.75"),
        reasoning="Because...",
        evidence=["quote"],
        target_platform="reddit",
        target_ref="t3_abc123",
    )
    await db_session.flush()

    r = await api_client.get(f"/api/v1/projects/{project_id}/content-items")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["status"] == "draft"
    assert body[0]["body"] == "A helpful reply."
    assert body[0]["confidence"] == "0.75"
    assert body[0]["evidence"] == ["quote"]


@pytest.mark.asyncio
async def test_list_content_items_filters_by_status(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    r = await api_client.get(f"/api/v1/projects/{project_id}/content-items?status=pending_review")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_content_item_returns_the_item(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    client = ContentDraftClient(db_session)
    item = await client.create_draft(
        project_id=uuid.UUID(project_id), type="reddit_reply", body="hi", confidence=Decimal("0.5")
    )
    await db_session.flush()

    r = await api_client.get(f"/api/v1/projects/{project_id}/content-items/{item.id}")
    assert r.status_code == 200
    assert r.json()["id"] == str(item.id)


@pytest.mark.asyncio
async def test_get_content_item_404s_for_an_unknown_id(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.get(f"/api/v1/projects/{project_id}/content-items/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_content_item_404s_for_an_item_belonging_to_another_project(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    from app.models.identity import Organization
    from app.models.project import Project
    from app.repositories.organization_repository import OrganizationRepository
    from app.repositories.project_repository import ProjectRepository

    other_org = await OrganizationRepository(db_session).add(
        Organization(name="Other", slug="other-org-content-items")
    )
    other_project = await ProjectRepository(db_session).add(
        Project(org_id=other_org.id, name="Other Project", slug="other-project-content-items")
    )
    client = ContentDraftClient(db_session)
    other_item = await client.create_draft(
        project_id=other_project.id, type="reddit_reply", body="hi", confidence=Decimal("0.5")
    )
    await db_session.flush()

    r = await api_client.get(f"/api/v1/projects/{project_id}/content-items/{other_item.id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_content_items_require_project_access(api_client: AsyncClient) -> None:
    r = await api_client.get(f"/api/v1/projects/{uuid.uuid4()}/content-items")
    assert r.status_code == 401
