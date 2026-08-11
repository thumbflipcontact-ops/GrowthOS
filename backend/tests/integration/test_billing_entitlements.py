"""Integration tests for the subscription entitlement gate — see
docs/billing/BILLING_ARCHITECTURE.md and app/core/entitlements.py.

`is_org_entitled`/`require_org_entitled` are pure-DB logic (no Polar SDK involved) tested
directly against real rows here. The API-level tests prove the gate is actually wired into
the two HTTP routes that spend paid, metered plugin capacity — creating a plugin connection
and triggering an agent run — using the same real-app-over-ASGITransport technique as
test_plugin_connections_api.py and test_agent_configs_api.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.entitlements import NO_CARD_TRIAL_DAYS, is_org_entitled, require_org_entitled
from app.core.errors import SubscriptionRequiredError
from app.models.billing import Subscription, SubscriptionStatus
from app.models.identity import Organization
from app.repositories.organization_repository import OrganizationRepository

pytestmark = pytest.mark.integration

# Comfortably past NO_CARD_TRIAL_DAYS — used to simulate an org whose no-card trial has
# already elapsed, since Organization.created_at defaults to "now" and can't be backdated
# through the real registration API.
_EXPIRED_TRIAL_CREATED_AT = datetime.now(UTC) - timedelta(days=NO_CARD_TRIAL_DAYS + 1)


async def _make_org(
    db_session,
    *,
    suffix: str | None = None,
    created_at: datetime | None = None,
    is_comped: bool = False,
) -> Organization:
    suffix = suffix or uuid.uuid4().hex[:8]
    org = Organization(name="Acme", slug=f"acme-entitle-{suffix}", is_comped=is_comped)
    if created_at is not None:
        org.created_at = created_at
    return await OrganizationRepository(db_session).add(org)


async def _add_subscription(db_session, org_id: uuid.UUID, status: SubscriptionStatus) -> None:
    suffix = uuid.uuid4().hex[:8]
    db_session.add(
        Subscription(
            org_id=org_id,
            polar_customer_id=f"cus_{suffix}",
            polar_subscription_id=f"sub_{suffix}",
            polar_product_id="prod_test",
            status=status,
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_fresh_org_with_no_subscription_is_entitled_via_no_card_trial(db_session) -> None:
    org = await _make_org(db_session)
    assert await is_org_entitled(db_session, org.id) is True


@pytest.mark.asyncio
async def test_org_with_no_subscription_and_elapsed_no_card_trial_is_not_entitled(db_session) -> None:
    org = await _make_org(db_session, created_at=_EXPIRED_TRIAL_CREATED_AT)
    assert await is_org_entitled(db_session, org.id) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE])
async def test_org_with_trial_or_active_subscription_is_entitled(db_session, status) -> None:
    org = await _make_org(db_session)
    await _add_subscription(db_session, org.id, status)
    assert await is_org_entitled(db_session, org.id) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [SubscriptionStatus.PAST_DUE, SubscriptionStatus.CANCELED, SubscriptionStatus.INCOMPLETE]
)
async def test_org_with_past_due_canceled_or_incomplete_subscription_is_not_entitled(
    db_session, status
) -> None:
    # A real subscription row always wins over the no-card trial fallback, even though these
    # orgs are freshly created (still within NO_CARD_TRIAL_DAYS) — a canceled/past_due/
    # incomplete Polar subscription must not be masked by trial-window math.
    org = await _make_org(db_session)
    await _add_subscription(db_session, org.id, status)
    assert await is_org_entitled(db_session, org.id) is False


@pytest.mark.asyncio
async def test_comped_org_with_no_subscription_is_entitled(db_session) -> None:
    org = await _make_org(db_session, is_comped=True, created_at=_EXPIRED_TRIAL_CREATED_AT)
    assert await is_org_entitled(db_session, org.id) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [SubscriptionStatus.PAST_DUE, SubscriptionStatus.CANCELED, SubscriptionStatus.INCOMPLETE]
)
async def test_comped_org_is_entitled_even_with_a_dead_subscription_row(db_session, status) -> None:
    """The whole point of is_comped: it must survive whatever happens to a real Polar
    subscription afterward — a later cancellation, a failed renewal charge, anything."""
    org = await _make_org(db_session, is_comped=True)
    await _add_subscription(db_session, org.id, status)
    assert await is_org_entitled(db_session, org.id) is True


@pytest.mark.asyncio
async def test_require_org_entitled_raises_402_once_no_card_trial_elapses(db_session) -> None:
    org = await _make_org(db_session, created_at=_EXPIRED_TRIAL_CREATED_AT)
    with pytest.raises(SubscriptionRequiredError) as exc_info:
        await require_org_entitled(db_session, org.id)
    assert exc_info.value.status_code == 402


@pytest.mark.asyncio
async def test_require_org_entitled_does_not_raise_for_a_fresh_org(db_session) -> None:
    org = await _make_org(db_session)
    await require_org_entitled(db_session, org.id)  # must not raise — no-card trial covers it


@pytest.mark.asyncio
async def test_require_org_entitled_does_not_raise_for_trialing_org(db_session) -> None:
    org = await _make_org(db_session)
    await _add_subscription(db_session, org.id, SubscriptionStatus.TRIALING)
    await require_org_entitled(db_session, org.id)  # must not raise


# --- API-level: the gate actually wired into create_plugin_connection / trigger_agent_run ---


@pytest_asyncio.fixture
async def api_client(db_session, _migrated_db):
    from app.api.deps import get_arq_redis, get_db
    from app.main import app

    class _FakeArqRedis:
        async def enqueue_job(self, *args: object, **kwargs: object) -> None:
            return None

    async def override_get_db():
        yield db_session

    async def override_get_arq_redis():
        return _FakeArqRedis()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_arq_redis] = override_get_arq_redis
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


async def _register_and_create_project(api_client: AsyncClient, db_session, *, suffix: str) -> tuple[str, str]:
    await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": f"acme-entitle-api-{suffix}",
            "email": f"owner-{suffix}@example.com",
            "name": "Owner",
            "password": "correct-horse-battery-staple",
        },
    )
    org = await OrganizationRepository(db_session).get_by_slug(f"acme-entitle-api-{suffix}")
    assert org is not None

    create = await api_client.post(
        f"/api/v1/orgs/{org.id}/projects",
        json={"name": "ScoutSEO", "slug": f"scoutseo-entitle-{suffix}"},
    )
    assert create.status_code == 201
    return create.json()["id"], str(org.id)


async def _expire_no_card_trial(db_session, org_id: str) -> None:
    """Registration always sets created_at to "now" server-side — simulate an org whose
    no-card trial has already elapsed by backdating it directly, the same technique
    _make_org's created_at override uses for the pure-DB tests above."""
    org = await OrganizationRepository(db_session).get(uuid.UUID(org_id))
    assert org is not None
    org.created_at = _EXPIRED_TRIAL_CREATED_AT
    await db_session.flush()


@pytest.mark.asyncio
async def test_create_plugin_connection_succeeds_via_no_card_trial(
    api_client: AsyncClient, db_session
) -> None:
    project_id, _org_id = await _register_and_create_project(api_client, db_session, suffix="pc1")

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections",
        json={"plugin_key": "dummy", "config": {"greeting": "hi"}, "capabilities_enabled": ["searchable"]},
    )

    assert r.status_code == 201


@pytest.mark.asyncio
async def test_create_plugin_connection_is_blocked_once_no_card_trial_elapses(
    api_client: AsyncClient, db_session
) -> None:
    project_id, org_id = await _register_and_create_project(api_client, db_session, suffix="pc3")
    await _expire_no_card_trial(db_session, org_id)

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections",
        json={"plugin_key": "dummy", "config": {"greeting": "hi"}, "capabilities_enabled": ["searchable"]},
    )

    assert r.status_code == 402
    assert r.json()["error"]["code"] == "subscription_required"


@pytest.mark.asyncio
async def test_create_plugin_connection_succeeds_with_a_trial_subscription(
    api_client: AsyncClient, db_session
) -> None:
    project_id, org_id = await _register_and_create_project(api_client, db_session, suffix="pc2")
    await _add_subscription(db_session, uuid.UUID(org_id), SubscriptionStatus.TRIALING)

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections",
        json={"plugin_key": "dummy", "config": {"greeting": "hi"}, "capabilities_enabled": ["searchable"]},
    )

    assert r.status_code == 201


@pytest.mark.asyncio
async def test_trigger_agent_run_succeeds_via_no_card_trial(
    api_client: AsyncClient, db_session
) -> None:
    project_id, _org_id = await _register_and_create_project(api_client, db_session, suffix="ar1")

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs/trigger"
    )

    assert r.status_code == 202


@pytest.mark.asyncio
async def test_trigger_agent_run_is_blocked_once_no_card_trial_elapses(
    api_client: AsyncClient, db_session
) -> None:
    project_id, org_id = await _register_and_create_project(api_client, db_session, suffix="ar3")
    await _expire_no_card_trial(db_session, org_id)

    r = await api_client.post(f"/api/v1/projects/{project_id}/agent-configs/dummy_agent/runs/trigger")

    assert r.status_code == 402
    assert r.json()["error"]["code"] == "subscription_required"


@pytest.mark.asyncio
async def test_trigger_agent_run_is_blocked_for_a_canceled_subscription(
    api_client: AsyncClient, db_session
) -> None:
    project_id, org_id = await _register_and_create_project(api_client, db_session, suffix="ar2")
    await _add_subscription(db_session, uuid.UUID(org_id), SubscriptionStatus.CANCELED)

    r = await api_client.post(f"/api/v1/projects/{project_id}/agent-configs/dummy_agent/runs/trigger")

    assert r.status_code == 402


@pytest.mark.asyncio
async def test_billing_status_for_fresh_org_with_no_subscription(
    api_client: AsyncClient, db_session
) -> None:
    _project_id, org_id = await _register_and_create_project(api_client, db_session, suffix="st1")

    r = await api_client.get(f"/api/v1/orgs/{org_id}/billing/status")

    assert r.status_code == 200
    body = r.json()
    assert body["has_subscription"] is False
    assert body["status"] is None
    assert body["is_entitled"] is True
    assert body["trial_ends_at"] is None
    assert body["current_period_end"] is None
    assert body["no_card_trial_ends_at"] is not None


@pytest.mark.asyncio
async def test_billing_status_for_org_with_elapsed_no_card_trial(
    api_client: AsyncClient, db_session
) -> None:
    _project_id, org_id = await _register_and_create_project(api_client, db_session, suffix="st3")
    await _expire_no_card_trial(db_session, org_id)

    r = await api_client.get(f"/api/v1/orgs/{org_id}/billing/status")

    assert r.status_code == 200
    body = r.json()
    assert body["has_subscription"] is False
    assert body["is_entitled"] is False
    assert body["no_card_trial_ends_at"] is not None


@pytest.mark.asyncio
async def test_billing_status_for_trialing_org(api_client: AsyncClient, db_session) -> None:
    _project_id, org_id = await _register_and_create_project(api_client, db_session, suffix="st2")
    await _add_subscription(db_session, uuid.UUID(org_id), SubscriptionStatus.TRIALING)

    r = await api_client.get(f"/api/v1/orgs/{org_id}/billing/status")

    assert r.status_code == 200
    body = r.json()
    assert body["has_subscription"] is True
    assert body["status"] == "trialing"
    assert body["is_entitled"] is True
    assert body["no_card_trial_ends_at"] is None
