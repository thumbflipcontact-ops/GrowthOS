"""End-to-end tests for the content-items API — see docs/api/API_DESIGN.md,
app/api/v1/content_items.py, docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md, and
docs/reviews/PUBLISHING_WORKFLOW_IMPLEMENTATION_REPORT.md.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.content import ContentItemStatus
from app.services.content_drafts import ContentDraftClient
from app.services.knowledge_base import KnowledgeBaseClient

pytestmark = pytest.mark.integration


class _FakeArqRedis:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, name: str, *args: object, **kwargs: object) -> None:
        self.enqueued.append((name, args, kwargs))


@pytest.fixture
def fake_arq_redis() -> _FakeArqRedis:
    return _FakeArqRedis()


@pytest_asyncio.fixture
async def api_client(db_session, _migrated_db, fake_arq_redis: _FakeArqRedis):
    from app.api.deps import get_arq_redis, get_db
    from app.main import app

    async def override_get_db():
        yield db_session

    async def override_get_arq_redis():
        return fake_arq_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_arq_redis] = override_get_arq_redis
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
async def test_list_and_get_content_items_include_the_full_source_post(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    knowledge_item, _ = await KnowledgeBaseClient(db_session).upsert_discovery(
        project_id=uuid.UUID(project_id),
        platform="twitter",
        url="https://twitter.com/i/web/status/1",
        tags=["seo"],
        confidence=Decimal("0.8"),
        body_excerpt="The full original tweet text, every single word of it, unabbreviated.",
    )
    item = await ContentDraftClient(db_session).create_draft(
        project_id=uuid.UUID(project_id),
        type="tweet",
        body="A helpful reply.",
        confidence=Decimal("0.75"),
        target_platform="twitter",
        knowledge_item_id=knowledge_item.id,
    )
    await db_session.flush()

    list_response = await api_client.get(f"/api/v1/projects/{project_id}/content-items")
    assert list_response.status_code == 200
    [body] = [i for i in list_response.json() if i["id"] == str(item.id)]
    assert body["source_body"] == (
        "The full original tweet text, every single word of it, unabbreviated."
    )

    get_response = await api_client.get(
        f"/api/v1/projects/{project_id}/content-items/{item.id}"
    )
    assert get_response.status_code == 200
    assert get_response.json()["source_body"] == (
        "The full original tweet text, every single word of it, unabbreviated."
    )


@pytest.mark.asyncio
async def test_content_item_without_a_knowledge_item_has_null_source_post(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    client = ContentDraftClient(db_session)
    item = await client.create_draft(
        project_id=uuid.UUID(project_id), type="reddit_reply", body="hi", confidence=Decimal("0.5")
    )
    await db_session.flush()

    r = await api_client.get(f"/api/v1/projects/{project_id}/content-items/{item.id}")
    assert r.status_code == 200
    assert r.json()["source_title"] is None
    assert r.json()["source_body"] is None


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


async def _make_pending_review_item(db_session, project_id: str):
    client = ContentDraftClient(db_session)
    item = await client.create_draft(
        project_id=uuid.UUID(project_id),
        type="reddit_reply",
        body="A helpful reply.",
        confidence=Decimal("0.75"),
        target_platform="reddit",
        target_ref="t3_abc123",
    )
    item.status = ContentItemStatus.PENDING_REVIEW
    await db_session.flush()
    return item


@pytest.mark.asyncio
async def test_approve_transitions_to_approved_and_enqueues_a_publish_job(
    api_client: AsyncClient, project_id: str, db_session, fake_arq_redis: _FakeArqRedis
) -> None:
    item = await _make_pending_review_item(db_session, project_id)
    original_version = item.version  # read before the API call refreshes this same object

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/approve",
        json={"version": original_version},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["version"] == original_version + 1

    assert len(fake_arq_redis.enqueued) == 1
    job_name, args, kwargs = fake_arq_redis.enqueued[0]
    assert job_name == "publish_content_item"
    assert args == (str(item.id),)
    assert kwargs["_job_id"] == f"publish-{item.id}"


@pytest.mark.asyncio
async def test_approve_skips_the_publish_job_for_a_twitter_item(
    api_client: AsyncClient, project_id: str, db_session, fake_arq_redis: _FakeArqRedis
) -> None:
    """X's own platform policy blocks a programmatic reply/quote unless the target post's
    author already @mentioned or quoted this account first — every organically-discovered
    post fails that by construction, so approving a twitter item must never enqueue a
    publish attempt that's guaranteed to 403. See app/api/v1/content_items.py's
    _MANUAL_PUBLISH_ONLY_PLATFORMS."""
    client = ContentDraftClient(db_session)
    item = await client.create_draft(
        project_id=uuid.UUID(project_id),
        type="tweet",
        body="A helpful reply.",
        confidence=Decimal("0.75"),
        target_platform="twitter",
        target_ref="182736450192834765",
    )
    item.status = ContentItemStatus.PENDING_REVIEW
    await db_session.flush()

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/approve",
        json={"version": item.version},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert fake_arq_redis.enqueued == []


@pytest.mark.asyncio
async def test_mark_published_works_for_an_approved_twitter_item(
    api_client: AsyncClient, project_id: str, db_session, fake_arq_redis: _FakeArqRedis
) -> None:
    client = ContentDraftClient(db_session)
    item = await client.create_draft(
        project_id=uuid.UUID(project_id),
        type="tweet",
        body="A helpful reply.",
        confidence=Decimal("0.75"),
        target_platform="twitter",
        target_ref="182736450192834765",
    )
    item.status = ContentItemStatus.PENDING_REVIEW
    await db_session.flush()

    approve = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/approve",
        json={"version": item.version},
    )
    assert approve.status_code == 200
    approved_version = approve.json()["version"]

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/mark-published",
        json={"version": approved_version},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "published"
    assert body["published_at"] is not None


@pytest.mark.asyncio
async def test_mark_published_rejects_an_item_still_pending_review(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    item = await _make_pending_review_item(db_session, project_id)

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/mark-published",
        json={"version": item.version},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_approve_rejects_a_draft_item_with_409(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    client = ContentDraftClient(db_session)
    item = await client.create_draft(
        project_id=uuid.UUID(project_id), type="reddit_reply", body="hi", confidence=Decimal("0.5")
    )
    await db_session.flush()

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/approve",
        json={"version": item.version},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invalid_state_transition"


@pytest.mark.asyncio
async def test_approve_rejects_a_stale_version_with_409(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    item = await _make_pending_review_item(db_session, project_id)

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/approve",
        json={"version": item.version + 1},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_reject_requires_a_reason(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    item = await _make_pending_review_item(db_session, project_id)

    missing_reason = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/reject",
        json={"version": item.version},
    )
    assert missing_reason.status_code == 422

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/reject",
        json={"version": item.version, "reason": "Too promotional."},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_archive_works_from_draft_without_a_reason(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    client = ContentDraftClient(db_session)
    item = await client.create_draft(
        project_id=uuid.UUID(project_id), type="reddit_reply", body="hi", confidence=Decimal("0.5")
    )
    await db_session.flush()

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/archive",
        json={"version": item.version},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_retry_publish_requires_approved_status(
    api_client: AsyncClient, project_id: str, db_session, fake_arq_redis: _FakeArqRedis
) -> None:
    item = await _make_pending_review_item(db_session, project_id)

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/retry-publish"
    )
    assert r.status_code == 409
    assert fake_arq_redis.enqueued == []


@pytest.mark.asyncio
async def test_retry_publish_enqueues_a_job_for_an_approved_item(
    api_client: AsyncClient, project_id: str, db_session, fake_arq_redis: _FakeArqRedis
) -> None:
    item = await _make_pending_review_item(db_session, project_id)
    item.status = ContentItemStatus.APPROVED
    item.publish_error = "a previous attempt failed"
    await db_session.flush()

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/retry-publish"
    )
    assert r.status_code == 202
    assert len(fake_arq_redis.enqueued) == 1
    assert fake_arq_redis.enqueued[0][2]["_job_id"] == f"publish-{item.id}"


@pytest.mark.asyncio
async def test_publish_attempts_list_is_empty_before_any_publish_attempt(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    item = await _make_pending_review_item(db_session, project_id)

    r = await api_client.get(
        f"/api/v1/projects/{project_id}/content-items/{item.id}/publish-attempts"
    )
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_publish_attempts_404s_for_an_unknown_item(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.get(
        f"/api/v1/projects/{project_id}/content-items/{uuid.uuid4()}/publish-attempts"
    )
    assert r.status_code == 404
