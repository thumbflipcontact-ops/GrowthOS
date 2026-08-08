"""End-to-end tests for the agent-configs API — see docs/api/API_DESIGN.md and
app/api/v1/agent_configs.py. `get_arq_redis` is overridden with an in-memory fake (same
technique `override_get_db` uses for the DB session) so the trigger endpoint's test never
needs a real Redis broker — see app/api/deps.py's get_arq_redis docstring.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


class _FakeArqRedis:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple]] = []

    async def enqueue_job(self, name: str, *args: object, **kwargs: object) -> None:
        self.enqueued.append((name, args))


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
    from app.models.billing import Subscription, SubscriptionStatus
    from app.repositories.organization_repository import OrganizationRepository

    await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-agent-configs",
            "email": "acowner@example.com",
            "name": "Owner",
            "password": "correct-horse-battery-staple",
        },
    )
    org = await OrganizationRepository(db_session).get_by_slug("acme-agent-configs")
    assert org is not None

    # trigger_agent_run gates on an active subscription/trial (app/api/deps.py's
    # require_active_subscription) — this test suite exercises the agent-configs API's own
    # mechanics, not billing, so the org it registers is entitled by default; see
    # test_billing_entitlements.py for the gate itself.
    db_session.add(
        Subscription(
            org_id=org.id,
            polar_customer_id=f"cus_{uuid.uuid4().hex[:8]}",
            polar_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
            polar_product_id="prod_test",
            status=SubscriptionStatus.TRIALING,
        )
    )
    await db_session.flush()

    create = await api_client.post(
        f"/api/v1/orgs/{org.id}/projects",
        json={"name": "ScoutSEO", "slug": "scoutseo-agent-configs"},
    )
    assert create.status_code == 201
    return create.json()["id"]


@pytest.mark.asyncio
async def test_upsert_agent_config_succeeds_with_valid_config(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.put(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder",
        json={"config": {"keywords": ["crawl budget"]}, "schedule_cron": "0 6 * * *"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["agent_key"] == "conversation_finder"
    assert body["config"] == {"keywords": ["crawl budget"]}
    assert body["schedule_cron"] == "0 6 * * *"
    assert body["enabled"] is True

    listed = await api_client.get(f"/api/v1/projects/{project_id}/agent-configs")
    assert listed.status_code == 200
    assert any(c["id"] == body["id"] for c in listed.json())


@pytest.mark.asyncio
async def test_upsert_agent_config_rejects_config_that_fails_the_schema(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.put(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder",
        json={"config": {"min_score_to_save": 5}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_upsert_agent_config_rejects_an_unknown_agent_key(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.put(
        f"/api/v1/projects/{project_id}/agent-configs/not-a-real-agent", json={"config": {}}
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_trigger_run_enqueues_a_job_and_creates_a_default_config(
    api_client: AsyncClient, project_id: str, fake_arq_redis: _FakeArqRedis
) -> None:
    r = await api_client.post(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs/trigger"
    )
    assert r.status_code == 202
    body = r.json()
    assert body["agent_key"] == "conversation_finder"
    assert body["status"] == "queued"

    assert len(fake_arq_redis.enqueued) == 1
    job_name, args = fake_arq_redis.enqueued[0]
    assert job_name == "run_scheduled_agent"
    assert args == (body["agent_config_id"],)


@pytest.mark.asyncio
async def test_trigger_run_reuses_an_existing_config_instead_of_creating_a_second_one(
    api_client: AsyncClient, project_id: str
) -> None:
    await api_client.put(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder",
        json={"config": {"keywords": ["crawl budget"]}},
    )
    r = await api_client.post(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs/trigger"
    )
    assert r.status_code == 202

    configs = await api_client.get(f"/api/v1/projects/{project_id}/agent-configs")
    matching = [c for c in configs.json() if c["agent_key"] == "conversation_finder"]
    assert len(matching) == 1
    assert matching[0]["config"] == {"keywords": ["crawl budget"]}  # untouched by the trigger


@pytest.mark.asyncio
async def test_trigger_run_rejects_an_unknown_agent_key(
    api_client: AsyncClient, project_id: str, fake_arq_redis: _FakeArqRedis
) -> None:
    r = await api_client.post(
        f"/api/v1/projects/{project_id}/agent-configs/not-a-real-agent/runs/trigger"
    )
    assert r.status_code == 404
    assert fake_arq_redis.enqueued == []


@pytest.mark.asyncio
async def test_list_runs_is_empty_before_any_trigger(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.get(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs"
    )
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_agent_configs_require_project_access(api_client: AsyncClient) -> None:
    r = await api_client.put(
        f"/api/v1/projects/{uuid.uuid4()}/agent-configs/conversation_finder", json={"config": {}}
    )
    assert r.status_code == 401  # not authenticated at all in this test
