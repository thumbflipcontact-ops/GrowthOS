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
    assert r.json() == {"runs": [], "total": 0}


async def _seed_runs(db_session, project_id: str, agent_config_id, count: int) -> list:
    import uuid as uuid_module

    from app.models.agent import AgentRun, AgentRunStatus

    runs = []
    for _ in range(count):
        run = AgentRun(
            agent_config_id=agent_config_id,
            project_id=uuid_module.UUID(project_id),
            agent_key="conversation_finder",
            status=AgentRunStatus.SUCCEEDED,
        )
        db_session.add(run)
        runs.append(run)
    await db_session.flush()
    return runs


@pytest.mark.asyncio
async def test_list_runs_paginates_with_limit_and_offset(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    from app.repositories.agent_repository import AgentConfigRepository

    config = await AgentConfigRepository(db_session).get_or_create(
        uuid.UUID(project_id), "conversation_finder"
    )
    await _seed_runs(db_session, project_id, config.id, 25)

    page1 = await api_client.get(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs",
        params={"limit": 20, "offset": 0},
    )
    page2 = await api_client.get(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs",
        params={"limit": 20, "offset": 20},
    )

    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["total"] == 25
    assert len(body1["runs"]) == 20

    body2 = page2.json()
    assert body2["total"] == 25
    assert len(body2["runs"]) == 5

    # No overlap between pages.
    ids1 = {r["id"] for r in body1["runs"]}
    ids2 = {r["id"] for r in body2["runs"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_list_runs_rejects_a_page_size_over_100(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.get(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs",
        params={"limit": 101},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_run_removes_it_from_the_list(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    from app.repositories.agent_repository import AgentConfigRepository

    config = await AgentConfigRepository(db_session).get_or_create(
        uuid.UUID(project_id), "conversation_finder"
    )
    [run] = await _seed_runs(db_session, project_id, config.id, 1)

    r = await api_client.delete(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs/{run.id}"
    )
    assert r.status_code == 204

    listed = await api_client.get(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs"
    )
    assert listed.json() == {"runs": [], "total": 0}


@pytest.mark.asyncio
async def test_delete_run_404s_for_a_run_belonging_to_another_project(
    api_client: AsyncClient, project_id: str, db_session
) -> None:
    from app.models.identity import Organization
    from app.models.project import Project
    from app.repositories.agent_repository import AgentConfigRepository
    from app.repositories.base import Repository
    from app.repositories.organization_repository import OrganizationRepository

    other_org = await OrganizationRepository(db_session).add(
        Organization(name="Other Org", slug="other-org-agent-runs")
    )

    class _ProjectRepository(Repository[Project]):
        model = Project

    other_project = await _ProjectRepository(db_session).add(
        Project(org_id=other_org.id, name="Other Project", slug="other-project-agent-runs")
    )
    other_config = await AgentConfigRepository(db_session).get_or_create(
        other_project.id, "conversation_finder"
    )
    [other_run] = await _seed_runs(db_session, str(other_project.id), other_config.id, 1)

    r = await api_client.delete(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs/{other_run.id}"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_run_404s_for_an_unknown_run_id(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.delete(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs/{uuid.uuid4()}"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_agent_configs_require_project_access(api_client: AsyncClient) -> None:
    r = await api_client.put(
        f"/api/v1/projects/{uuid.uuid4()}/agent-configs/conversation_finder", json={"config": {}}
    )
    assert r.status_code == 401  # not authenticated at all in this test
