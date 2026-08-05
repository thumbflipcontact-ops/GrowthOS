"""End-to-end proof of the plugin-connections API — the piece the Platform Readiness Review
found missing: previously there was no way to actually connect an installed plugin to a
project. Uses the real `dummy` fixture plugin (installed editable, see
plugins/dummy/pyproject.toml) so config_schema validation runs against a real pydantic model,
not a mock. See docs/api/API_DESIGN.md and app/services/plugin_connection.py.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
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
    from app.models.billing import Subscription, SubscriptionStatus
    from app.repositories.organization_repository import OrganizationRepository

    await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-plugin-conn",
            "email": "connowner@example.com",
            "name": "Owner",
            "password": "correct-horse-battery-staple",
        },
    )
    org = await OrganizationRepository(db_session).get_by_slug("acme-plugin-conn")
    assert org is not None

    # create_plugin_connection gates on an active subscription/trial
    # (app/api/deps.py's require_active_subscription) — this test suite exercises the
    # plugin-connections API's own mechanics, not billing, so the org it registers is
    # entitled by default; see test_billing_entitlements.py for the gate itself.
    suffix = uuid.uuid4().hex[:8]
    db_session.add(
        Subscription(
            org_id=org.id,
            polar_customer_id=f"cus_{suffix}",
            polar_subscription_id=f"sub_{suffix}",
            polar_product_id="prod_test",
            status=SubscriptionStatus.TRIALING,
        )
    )
    await db_session.flush()

    create = await api_client.post(
        f"/api/v1/orgs/{org.id}/projects", json={"name": "ScoutSEO", "slug": "scoutseo-plugin-conn"}
    )
    assert create.status_code == 201
    return create.json()["id"]


@pytest.mark.asyncio
async def test_create_plugin_connection_succeeds_with_valid_config(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections",
        json={"plugin_key": "dummy", "config": {"greeting": "hi"}, "capabilities_enabled": ["searchable"]},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["plugin_key"] == "dummy"
    assert body["config"] == {"greeting": "hi"}
    assert body["capabilities_enabled"] == ["searchable"]
    assert body["status"] == "disconnected"  # no credentials submitted — see schema docstring

    listed = await api_client.get(f"/api/v1/projects/{project_id}/plugin-connections")
    assert listed.status_code == 200
    assert any(c["id"] == body["id"] for c in listed.json())


@pytest.mark.asyncio
async def test_create_plugin_connection_rejects_config_that_fails_the_schema(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections",
        json={"plugin_key": "dummy", "config": {"greeting": 12345}},  # schema requires str
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_create_plugin_connection_rejects_unknown_plugin(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections",
        json={"plugin_key": "not-a-real-plugin", "config": {}},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_plugin_connection_rejects_capability_the_plugin_does_not_declare(
    api_client: AsyncClient, project_id: str
) -> None:
    r = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections",
        json={"plugin_key": "dummy", "config": {}, "capabilities_enabled": ["publishable"]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_create_plugin_connection_rejects_duplicate_connection(
    api_client: AsyncClient, project_id: str
) -> None:
    first = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections",
        json={"plugin_key": "dummy", "config": {}},
    )
    assert first.status_code == 201

    second = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections",
        json={"plugin_key": "dummy", "config": {}},
    )
    assert second.status_code == 422


@pytest.mark.asyncio
async def test_plugin_connections_require_project_access(api_client: AsyncClient) -> None:
    r = await api_client.post(
        f"/api/v1/projects/{uuid.uuid4()}/plugin-connections",
        json={"plugin_key": "dummy", "config": {}},
    )
    assert r.status_code == 401  # not authenticated at all in this test
