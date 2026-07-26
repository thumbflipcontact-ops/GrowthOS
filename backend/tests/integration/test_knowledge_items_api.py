"""End-to-end tests for the knowledge-items read API — see docs/api/API_DESIGN.md and
app/api/v1/knowledge_items.py.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.services.knowledge_base import KnowledgeBaseClient

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
            "org_slug": "acme-knowledge-items",
            "email": "kiowner@example.com",
            "name": "Owner",
            "password": "correct-horse-battery-staple",
        },
    )
    org = await OrganizationRepository(db_session).get_by_slug("acme-knowledge-items")
    assert org is not None

    create = await api_client.post(
        f"/api/v1/orgs/{org.id}/projects",
        json={"name": "ScoutSEO", "slug": "scoutseo-knowledge-items"},
    )
    assert create.status_code == 201
    return create.json()["id"]


@pytest.mark.asyncio
async def test_list_knowledge_items_returns_discovered_items(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    import uuid

    client = KnowledgeBaseClient(db_session)
    await client.upsert_discovery(
        project_id=uuid.UUID(project_id),
        platform="reddit",
        url="https://reddit.com/r/SEO/1",
        tags=["crawl budget"],
        confidence=Decimal("0.75"),
    )
    await db_session.flush()

    r = await api_client.get(f"/api/v1/projects/{project_id}/knowledge-items")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["platform"] == "reddit"
    assert body[0]["tags"] == ["crawl budget"]
    assert body[0]["buying_intent"] == "none"


@pytest.mark.asyncio
async def test_list_knowledge_items_filters_by_tag(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    import uuid

    client = KnowledgeBaseClient(db_session)
    await client.upsert_discovery(
        project_id=uuid.UUID(project_id),
        platform="reddit",
        url="https://reddit.com/r/SEO/a",
        tags=["crawl budget"],
        confidence=Decimal("0.5"),
    )
    await client.upsert_discovery(
        project_id=uuid.UUID(project_id),
        platform="reddit",
        url="https://reddit.com/r/SEO/b",
        tags=["canonical tags"],
        confidence=Decimal("0.5"),
    )
    await db_session.flush()

    r = await api_client.get(f"/api/v1/projects/{project_id}/knowledge-items?tag=canonical+tags")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["url"] == "https://reddit.com/r/SEO/b"


@pytest.mark.asyncio
async def test_list_knowledge_items_is_empty_for_a_new_project(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.get(f"/api/v1/projects/{project_id}/knowledge-items")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_knowledge_items_require_project_access(api_client: AsyncClient) -> None:
    import uuid

    r = await api_client.get(f"/api/v1/projects/{uuid.uuid4()}/knowledge-items")
    assert r.status_code == 401
