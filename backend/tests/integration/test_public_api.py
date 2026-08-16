"""End-to-end tests for the public /public/v1 API — see app/api/public/v1/*, and
app/api/deps.py's require_api_key_project (the auth dependency every route here shares).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.content import ContentItemStatus
from app.repositories.organization_repository import OrganizationRepository
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
async def project_and_key(api_client: AsyncClient, db_session) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": f"acme-public-api-{suffix}",
            "email": f"owner-{suffix}@example.com",
            "name": "Owner",
            "password": "correct-horse-battery-staple",
        },
    )
    org = await OrganizationRepository(db_session).get_by_slug(f"acme-public-api-{suffix}")
    assert org is not None

    create = await api_client.post(
        f"/api/v1/orgs/{org.id}/projects",
        json={"name": "ScoutSEO", "slug": f"scoutseo-public-api-{suffix}"},
    )
    assert create.status_code == 201
    project_id = create.json()["id"]

    key_resp = await api_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "n8n integration"}
    )
    assert key_resp.status_code == 201
    return project_id, key_resp.json()["full_key"]


def _auth(full_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {full_key}"}


async def _make_pending_review_item(db_session, project_id: str, **overrides: object):
    client = ContentDraftClient(db_session)
    item = await client.create_draft(
        project_id=uuid.UUID(project_id),
        type=overrides.pop("type", "tweet"),
        body=overrides.pop("body", "A helpful reply."),
        confidence=Decimal("0.75"),
        target_platform=overrides.pop("target_platform", "reddit"),
    )
    item.status = ContentItemStatus.PENDING_REVIEW
    await db_session.flush()
    return item


# --- Auth ---


@pytest.mark.asyncio
async def test_missing_authorization_header_is_401(api_client: AsyncClient) -> None:
    r = await api_client.get("/public/v1/conversations")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_malformed_authorization_header_is_401(api_client: AsyncClient) -> None:
    r = await api_client.get("/public/v1/conversations", headers={"Authorization": "not-bearer x"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_unknown_key_is_401(api_client: AsyncClient) -> None:
    r = await api_client.get("/public/v1/conversations", headers=_auth("thr_totallymadeup"))
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_revoked_key_is_401(
    api_client: AsyncClient, project_and_key: tuple[str, str]
) -> None:
    project_id, full_key = project_and_key
    keys = await api_client.get(f"/api/v1/projects/{project_id}/api-keys")
    key_id = keys.json()[0]["id"]

    await api_client.post(f"/api/v1/projects/{project_id}/api-keys/{key_id}/revoke")

    r = await api_client.get("/public/v1/conversations", headers=_auth(full_key))
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429(
    api_client: AsyncClient, project_and_key: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.deps as deps_module
    from app.core.rate_limit import RateLimiter

    monkeypatch.setattr(
        deps_module, "_public_api_limiter", RateLimiter(capacity=1, refill_rate=0.0001)
    )
    _project_id, full_key = project_and_key

    first = await api_client.get("/public/v1/conversations", headers=_auth(full_key))
    assert first.status_code == 200
    second = await api_client.get("/public/v1/conversations", headers=_auth(full_key))
    assert second.status_code == 429


# --- Conversations / drafts / replies ---


@pytest.mark.asyncio
async def test_list_conversations_returns_real_data(
    api_client: AsyncClient, project_and_key: tuple[str, str], db_session
) -> None:
    project_id, full_key = project_and_key
    await KnowledgeBaseClient(db_session).upsert_discovery(
        project_id=uuid.UUID(project_id),
        platform="twitter",
        url="https://twitter.com/i/web/status/1",
        tags=["seo"],
        confidence=Decimal("0.8"),
        title="Someone asking about crawl budget",
    )
    await db_session.flush()

    r = await api_client.get("/public/v1/conversations", headers=_auth(full_key))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["title"] == "Someone asking about crawl budget"


@pytest.mark.asyncio
async def test_list_drafts_defaults_to_pending_review(
    api_client: AsyncClient, project_and_key: tuple[str, str], db_session
) -> None:
    project_id, full_key = project_and_key
    await _make_pending_review_item(db_session, project_id)
    # A plain draft (never submitted for review) must not show up in the default listing.
    await ContentDraftClient(db_session).create_draft(
        project_id=uuid.UUID(project_id), type="tweet", body="still drafting", confidence=Decimal("0.5")
    )
    await db_session.flush()

    r = await api_client.get("/public/v1/drafts", headers=_auth(full_key))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["status"] == "pending_review"


@pytest.mark.asyncio
async def test_approve_draft_attributes_to_key_creator_and_enqueues_publish(
    api_client: AsyncClient,
    project_and_key: tuple[str, str],
    db_session,
    fake_arq_redis: _FakeArqRedis,
) -> None:
    project_id, full_key = project_and_key
    item = await _make_pending_review_item(db_session, project_id, target_platform="reddit")

    from app.repositories.api_key_repository import ApiKeyRepository

    keys = await ApiKeyRepository(db_session).list_by_project(uuid.UUID(project_id))
    assert len(keys) == 1
    creator_id = keys[0].created_by_user_id
    assert creator_id is not None

    r = await api_client.post(
        f"/public/v1/drafts/{item.id}/approve", headers=_auth(full_key)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["reviewed_by_user_id"] == str(creator_id)
    assert len(fake_arq_redis.enqueued) == 1  # reddit is publishable, unlike twitter


@pytest.mark.asyncio
async def test_approve_draft_skips_publish_job_for_twitter(
    api_client: AsyncClient,
    project_and_key: tuple[str, str],
    db_session,
    fake_arq_redis: _FakeArqRedis,
) -> None:
    project_id, full_key = project_and_key
    item = await _make_pending_review_item(db_session, project_id, target_platform="twitter")

    r = await api_client.post(f"/public/v1/drafts/{item.id}/approve", headers=_auth(full_key))
    assert r.status_code == 200
    assert fake_arq_redis.enqueued == []


@pytest.mark.asyncio
async def test_reject_draft_attributes_to_key_creator(
    api_client: AsyncClient, project_and_key: tuple[str, str], db_session
) -> None:
    project_id, full_key = project_and_key
    item = await _make_pending_review_item(db_session, project_id)

    r = await api_client.post(
        f"/public/v1/drafts/{item.id}/reject",
        json={"reason": "not relevant"},
        headers=_auth(full_key),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected"
    assert body["reviewed_by_user_id"] is not None


@pytest.mark.asyncio
async def test_list_replies_returns_only_published_items(
    api_client: AsyncClient, project_and_key: tuple[str, str], db_session
) -> None:
    project_id, full_key = project_and_key
    published = await ContentDraftClient(db_session).create_draft(
        project_id=uuid.UUID(project_id), type="tweet", body="already posted", confidence=Decimal("0.9")
    )
    published.status = ContentItemStatus.PUBLISHED
    await _make_pending_review_item(db_session, project_id)  # must not show up
    await db_session.flush()

    r = await api_client.get("/public/v1/replies", headers=_auth(full_key))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["id"] == str(published.id)


# --- Webhook subscriptions ---


@pytest.mark.asyncio
async def test_create_list_and_delete_webhook_subscription(
    api_client: AsyncClient, project_and_key: tuple[str, str]
) -> None:
    _project_id, full_key = project_and_key

    create = await api_client.post(
        "/public/v1/webhook-subscriptions",
        json={"target_url": "https://hooks.example.com/threadly", "event_types": ["conversation.discovered"]},
        headers=_auth(full_key),
    )
    assert create.status_code == 201
    body = create.json()
    assert body["secret"]
    subscription_id = body["id"]

    listing = await api_client.get("/public/v1/webhook-subscriptions", headers=_auth(full_key))
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert "secret" not in listing.json()[0]

    delete = await api_client.delete(
        f"/public/v1/webhook-subscriptions/{subscription_id}", headers=_auth(full_key)
    )
    assert delete.status_code == 204

    listing_after = await api_client.get("/public/v1/webhook-subscriptions", headers=_auth(full_key))
    assert listing_after.json()[0]["enabled"] is False


@pytest.mark.asyncio
async def test_create_webhook_subscription_rejects_unsafe_url(
    api_client: AsyncClient, project_and_key: tuple[str, str]
) -> None:
    _project_id, full_key = project_and_key

    r = await api_client.post(
        "/public/v1/webhook-subscriptions",
        json={"target_url": "http://localhost:8000/x", "event_types": ["conversation.discovered"]},
        headers=_auth(full_key),
    )
    assert r.status_code == 422
