"""Integration tests for BillingService — see docs/billing/BILLING_ARCHITECTURE.md.

`create_checkout_session`/`create_portal_session` monkeypatch `billing_service.Polar` with a
fake async-context-manager client (same "fake double, not a mocked HTTP layer" technique
plugins/reddit/tests/test_plugin.py uses for RedditClient) so no real network call ever
happens. `handle_webhook_event` monkeypatches `billing_service.validate_event` to return a
real `polar_sdk` payload object constructed directly — this exercises the actual sync logic
against real Pydantic models, only the signature verification itself is bypassed (that's
`validate_event`'s own job, not this service's).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from polar_sdk.models import Subscription as PolarSubscription
from polar_sdk.models import SubscriptionStatus as PolarSubscriptionStatus
from polar_sdk.models import (
    WebhookCheckoutUpdatedPayload,
    WebhookSubscriptionCreatedPayload,
    WebhookSubscriptionUpdatedPayload,
)
from polar_sdk.models.checkout import Checkout
from polar_sdk.models.subscriptioncustomer import SubscriptionCustomer
from polar_sdk.webhooks import WebhookVerificationError

from app.core.config import Settings
from app.core.errors import BillingNotConfigured, NotFoundError
from app.models.billing import Subscription, SubscriptionStatus
from app.models.identity import Organization
from app.repositories.billing_repository import SubscriptionRepository
from app.repositories.organization_repository import OrganizationRepository
from app.services.billing_service import BillingService

pytestmark = pytest.mark.integration


def _settings(**overrides: object) -> Settings:
    defaults = dict(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
        polar_access_token="polar_at_test",
        polar_webhook_secret="whsec_test",
        polar_product_id="prod_test_standard",
        polar_product_id_tier1="prod_test_founding",
        polar_product_id_tier2="prod_test_early",
    )
    defaults.update(overrides)
    return Settings(**defaults)


async def _make_org(db_session, *, suffix: str | None = None) -> Organization:
    suffix = suffix or uuid.uuid4().hex[:8]
    return await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-billing-{suffix}")
    )


async def _seed_subscriptions(db_session, count: int) -> None:
    """Fills the tiered-pricing "signup order" counter with `count` unrelated orgs' rows —
    see app/core/pricing.py and BillingService._resolve_product_id."""
    for _ in range(count):
        org = await _make_org(db_session)
        db_session.add(
            Subscription(
                org_id=org.id,
                polar_customer_id=f"cus_{uuid.uuid4().hex[:8]}",
                polar_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
                polar_product_id="prod_test_founding",
                status=SubscriptionStatus.TRIALING,
            )
        )
    await db_session.flush()


def _polar_customer(external_id: str | None) -> SubscriptionCustomer:
    # model_construct (not model_validate) deliberately — this platform's own sync logic
    # (BillingService._sync_subscription) only ever reads `.external_id` off this object;
    # building a fully schema-valid SubscriptionCustomer would mean tracking every field
    # Polar's SDK happens to require today, none of which this test is actually about.
    return SubscriptionCustomer.model_construct(external_id=external_id)


def _polar_subscription(
    *,
    subscription_id: str = "sub_polar_1",
    external_customer_id: str | None,
    status: PolarSubscriptionStatus = PolarSubscriptionStatus.TRIALING,
    product_id: str = "prod_test",
) -> PolarSubscription:
    # model_construct, same reasoning as _polar_customer above — only the fields
    # BillingService._sync_subscription/_apply-equivalent logic actually reads are set.
    now = datetime.now(UTC)
    return PolarSubscription.model_construct(
        id=subscription_id,
        status=status,
        customer_id="cus_polar_123",
        product_id=product_id,
        trial_end=now + timedelta(days=7),
        current_period_end=now + timedelta(days=30),
        canceled_at=None,
        customer=_polar_customer(external_customer_id),
    )


class _FakeResource:
    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[dict] = []

    async def create_async(self, *, request):  # noqa: ANN001
        self.calls.append({"request": request})
        return self._response


class _FakePolar:
    """Test double for polar_sdk.Polar — an async context manager exposing the two resources
    BillingService actually calls, so no real network call ever happens."""

    def __init__(self, checkout_response=None, customer_session_response=None):  # noqa: ANN001
        self.checkouts = _FakeResource(checkout_response)
        self.customer_sessions = _FakeResource(customer_session_response)

    def __call__(self, *, access_token, server):  # noqa: ANN001
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def _install_fake_polar(monkeypatch, fake: _FakePolar) -> None:
    import app.services.billing_service as billing_service_module

    monkeypatch.setattr(billing_service_module, "Polar", fake)


@pytest.mark.asyncio
async def test_create_checkout_session_returns_url(monkeypatch, db_session) -> None:
    org = await _make_org(db_session)
    fake = _FakePolar(checkout_response=Checkout.model_construct(url="https://polar.sh/checkout/abc"))
    _install_fake_polar(monkeypatch, fake)

    url = await BillingService(db_session, _settings()).create_checkout_session(
        org=org, user_email="founder@example.com"
    )

    assert url == "https://polar.sh/checkout/abc"
    call = fake.checkouts.calls[0]["request"]
    # No one has checked out yet — this org is the 1st, so it lands in the founding tier.
    assert call.products == ["prod_test_founding"]
    assert call.external_customer_id == str(org.id)
    assert call.allow_trial is True


@pytest.mark.asyncio
async def test_create_checkout_session_raises_when_not_configured(db_session) -> None:
    org = await _make_org(db_session)
    settings = _settings(polar_access_token=None)

    with pytest.raises(BillingNotConfigured):
        await BillingService(db_session, settings).create_checkout_session(
            org=org, user_email="founder@example.com"
        )


@pytest.mark.asyncio
async def test_create_checkout_session_selects_early_tier_once_founding_fills(
    monkeypatch, db_session
) -> None:
    await _seed_subscriptions(db_session, 5)
    org = await _make_org(db_session)
    fake = _FakePolar(checkout_response=Checkout.model_construct(url="https://polar.sh/checkout/abc"))
    _install_fake_polar(monkeypatch, fake)

    await BillingService(db_session, _settings()).create_checkout_session(
        org=org, user_email="founder@example.com"
    )

    assert fake.checkouts.calls[0]["request"].products == ["prod_test_early"]


@pytest.mark.asyncio
async def test_create_checkout_session_selects_standard_tier_once_early_fills(
    monkeypatch, db_session
) -> None:
    await _seed_subscriptions(db_session, 15)
    org = await _make_org(db_session)
    fake = _FakePolar(checkout_response=Checkout.model_construct(url="https://polar.sh/checkout/abc"))
    _install_fake_polar(monkeypatch, fake)

    await BillingService(db_session, _settings()).create_checkout_session(
        org=org, user_email="founder@example.com"
    )

    assert fake.checkouts.calls[0]["request"].products == ["prod_test_standard"]


@pytest.mark.asyncio
async def test_create_checkout_session_reuses_existing_org_product_id(monkeypatch, db_session) -> None:
    """An org re-opening checkout (e.g. after an abandoned session) keeps whatever tier it was
    originally assigned — its price is permanent, and it must not count its own row against
    itself on recomputation."""
    org = await _make_org(db_session)
    db_session.add(
        Subscription(
            org_id=org.id,
            polar_customer_id="cus_existing",
            polar_subscription_id="sub_existing",
            polar_product_id="prod_test_founding",
            status=SubscriptionStatus.CANCELED,
        )
    )
    await db_session.flush()
    await _seed_subscriptions(db_session, 20)  # far past every tier's capacity
    fake = _FakePolar(checkout_response=Checkout.model_construct(url="https://polar.sh/checkout/abc"))
    _install_fake_polar(monkeypatch, fake)

    await BillingService(db_session, _settings()).create_checkout_session(
        org=org, user_email="founder@example.com"
    )

    assert fake.checkouts.calls[0]["request"].products == ["prod_test_founding"]


@pytest.mark.asyncio
async def test_create_checkout_session_raises_when_tier_product_not_configured(db_session) -> None:
    org = await _make_org(db_session)
    settings = _settings(polar_product_id_tier1=None)

    with pytest.raises(BillingNotConfigured):
        await BillingService(db_session, settings).create_checkout_session(
            org=org, user_email="founder@example.com"
        )


@pytest.mark.asyncio
async def test_get_pricing_tiers_reflects_live_signup_count(db_session) -> None:
    await _seed_subscriptions(db_session, 6)  # founding sold out, 1 into early

    statuses = await BillingService(db_session, _settings()).get_pricing_tiers()

    founding, early, standard = statuses
    assert founding.spots_left == 0
    assert founding.is_sold_out is True
    assert early.spots_taken == 1
    assert early.spots_left == 9
    assert early.is_current is True
    assert standard.spots_taken == 0
    assert standard.is_current is False


@pytest.mark.asyncio
async def test_create_portal_session_returns_url(monkeypatch, db_session) -> None:
    org = await _make_org(db_session)
    db_session.add(
        Subscription(
            org_id=org.id,
            polar_customer_id="cus_polar_123",
            polar_subscription_id="sub_polar_1",
            polar_product_id="prod_test",
            status=SubscriptionStatus.TRIALING,
        )
    )
    await db_session.flush()

    class _FakeCustomerSession:
        customer_portal_url = "https://polar.sh/portal/xyz"

    fake = _FakePolar(customer_session_response=_FakeCustomerSession())
    _install_fake_polar(monkeypatch, fake)

    url = await BillingService(db_session, _settings()).create_portal_session(org_id=org.id)

    assert url == "https://polar.sh/portal/xyz"


@pytest.mark.asyncio
async def test_create_portal_session_without_subscription_raises_not_found(db_session) -> None:
    org = await _make_org(db_session)

    with pytest.raises(NotFoundError):
        await BillingService(db_session, _settings()).create_portal_session(org_id=org.id)


@pytest.mark.asyncio
async def test_webhook_signature_failure_raises(monkeypatch, db_session) -> None:
    import app.services.billing_service as billing_service_module

    def fake_validate_event(payload, headers, secret):  # noqa: ANN001
        raise WebhookVerificationError("bad signature")

    monkeypatch.setattr(billing_service_module, "validate_event", fake_validate_event)

    from app.core.errors import ValidationError

    with pytest.raises(ValidationError):
        await BillingService(db_session, _settings()).handle_webhook_event(
            payload=b"{}", headers={}
        )


@pytest.mark.asyncio
async def test_webhook_creates_a_new_subscription_row(monkeypatch, db_session) -> None:
    import app.services.billing_service as billing_service_module

    org = await _make_org(db_session)
    webhook_payload = WebhookSubscriptionCreatedPayload(
        timestamp=datetime.now(UTC),
        data=_polar_subscription(external_customer_id=str(org.id)),
    )
    monkeypatch.setattr(
        billing_service_module, "validate_event", lambda payload, headers, secret: webhook_payload
    )

    await BillingService(db_session, _settings()).handle_webhook_event(payload=b"{}", headers={})

    subscription = await SubscriptionRepository(db_session).get_by_org(org.id)
    assert subscription is not None
    assert subscription.status == SubscriptionStatus.TRIALING
    assert subscription.polar_subscription_id == "sub_polar_1"
    assert subscription.is_entitled is True


@pytest.mark.asyncio
async def test_webhook_updates_an_existing_subscription_row(monkeypatch, db_session) -> None:
    import app.services.billing_service as billing_service_module

    org = await _make_org(db_session)
    db_session.add(
        Subscription(
            org_id=org.id,
            polar_customer_id="cus_polar_123",
            polar_subscription_id="sub_polar_1",
            polar_product_id="prod_test",
            status=SubscriptionStatus.TRIALING,
        )
    )
    await db_session.flush()

    webhook_payload = WebhookSubscriptionUpdatedPayload(
        timestamp=datetime.now(UTC),
        data=_polar_subscription(
            external_customer_id=str(org.id), status=PolarSubscriptionStatus.ACTIVE
        ),
    )
    monkeypatch.setattr(
        billing_service_module, "validate_event", lambda payload, headers, secret: webhook_payload
    )

    await BillingService(db_session, _settings()).handle_webhook_event(payload=b"{}", headers={})

    subscription = await SubscriptionRepository(db_session).get_by_org(org.id)
    assert subscription.status == SubscriptionStatus.ACTIVE


@pytest.mark.asyncio
async def test_webhook_past_due_is_not_entitled(monkeypatch, db_session) -> None:
    import app.services.billing_service as billing_service_module

    org = await _make_org(db_session)
    webhook_payload = WebhookSubscriptionCreatedPayload(
        timestamp=datetime.now(UTC),
        data=_polar_subscription(
            external_customer_id=str(org.id), status=PolarSubscriptionStatus.PAST_DUE
        ),
    )
    monkeypatch.setattr(
        billing_service_module, "validate_event", lambda payload, headers, secret: webhook_payload
    )

    await BillingService(db_session, _settings()).handle_webhook_event(payload=b"{}", headers={})

    subscription = await SubscriptionRepository(db_session).get_by_org(org.id)
    assert subscription.is_entitled is False


@pytest.mark.asyncio
async def test_webhook_unrecognized_status_falls_back_to_canceled(monkeypatch, db_session) -> None:
    import app.services.billing_service as billing_service_module

    org = await _make_org(db_session)
    webhook_payload = WebhookSubscriptionCreatedPayload(
        timestamp=datetime.now(UTC),
        data=_polar_subscription(
            external_customer_id=str(org.id), status=PolarSubscriptionStatus.PAUSED
        ),
    )
    monkeypatch.setattr(
        billing_service_module, "validate_event", lambda payload, headers, secret: webhook_payload
    )

    await BillingService(db_session, _settings()).handle_webhook_event(payload=b"{}", headers={})

    subscription = await SubscriptionRepository(db_session).get_by_org(org.id)
    assert subscription.status == SubscriptionStatus.CANCELED
    assert subscription.is_entitled is False


@pytest.mark.asyncio
async def test_webhook_subscription_with_no_external_customer_id_is_skipped(
    monkeypatch, db_session
) -> None:
    import app.services.billing_service as billing_service_module

    webhook_payload = WebhookSubscriptionCreatedPayload(
        timestamp=datetime.now(UTC), data=_polar_subscription(external_customer_id=None)
    )
    monkeypatch.setattr(
        billing_service_module, "validate_event", lambda payload, headers, secret: webhook_payload
    )

    # Must not raise — logged and skipped, see BillingService._sync_subscription.
    await BillingService(db_session, _settings()).handle_webhook_event(payload=b"{}", headers={})

    subscription = await SubscriptionRepository(db_session).get_by_polar_subscription_id(
        "sub_polar_1"
    )
    assert subscription is None


@pytest.mark.asyncio
async def test_webhook_ignores_non_subscription_event_types(monkeypatch, db_session) -> None:
    import app.services.billing_service as billing_service_module

    checkout_payload = WebhookCheckoutUpdatedPayload(
        timestamp=datetime.now(UTC), data=Checkout.model_construct(id="checkout_1")
    )
    monkeypatch.setattr(
        billing_service_module,
        "validate_event",
        lambda payload, headers, secret: checkout_payload,
    )

    # Must not raise and must not touch the subscriptions table.
    await BillingService(db_session, _settings()).handle_webhook_event(payload=b"{}", headers={})
