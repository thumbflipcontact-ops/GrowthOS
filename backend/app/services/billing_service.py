"""Polar orchestration — Checkout Sessions, the Customer Portal, and webhook-driven
subscription sync. See docs/billing/BILLING_ARCHITECTURE.md.

This is the only module in the codebase that imports `polar_sdk` — the same "one boundary
module" principle as `app/core/oauth/client.py` for OAuth providers. `app/core/entitlements.py`
(what job bodies and API routes actually gate on) never imports this module or the `polar_sdk`
package; it only reads the `subscriptions` table this service keeps in sync.

Card collection stays entirely on Polar's hosted Checkout/Customer Portal pages — Polar is a
merchant-of-record, so this platform never sees a card number and never handles tax/VAT
compliance itself.
"""

from __future__ import annotations

import uuid

import structlog
from polar_sdk import Polar
from polar_sdk.models import (
    CheckoutCreate,
    CustomerSessionCustomerExternalIDCreate,
    WebhookSubscriptionActivePayload,
    WebhookSubscriptionCanceledPayload,
    WebhookSubscriptionCreatedPayload,
    WebhookSubscriptionPastDuePayload,
    WebhookSubscriptionRevokedPayload,
    WebhookSubscriptionUncanceledPayload,
    WebhookSubscriptionUpdatedPayload,
)
from polar_sdk.models import (
    Subscription as PolarSubscription,
)
from polar_sdk.webhooks import WebhookUnknownTypeError, WebhookVerificationError, validate_event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BillingNotConfigured, NotFoundError, ValidationError
from app.core.pricing import PricingTier, TierStatus, tier_for_count, tier_statuses
from app.models.audit import AuditLog
from app.models.billing import Subscription, SubscriptionStatus
from app.models.identity import Organization
from app.repositories.billing_repository import SubscriptionRepository

logger = structlog.get_logger()

# Every webhook payload type whose `.data` is a Subscription — Polar fires a distinct event
# per lifecycle transition (created, active, past_due, canceled, uncanceled, revoked, plus the
# catch-all `updated`) rather than one generic "subscription changed" event like Stripe's.
# All of them are synced identically here: re-read the Subscription's current state and
# upsert, never branch behavior per event type. See handle_webhook_event below.
_SUBSCRIPTION_PAYLOAD_TYPES = (
    WebhookSubscriptionCreatedPayload,
    WebhookSubscriptionUpdatedPayload,
    WebhookSubscriptionActivePayload,
    WebhookSubscriptionCanceledPayload,
    WebhookSubscriptionPastDuePayload,
    WebhookSubscriptionUncanceledPayload,
    WebhookSubscriptionRevokedPayload,
)


class BillingService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.subscriptions = SubscriptionRepository(session)

    async def create_checkout_session(self, *, org: Organization, user_email: str) -> str:
        """Returns a Polar-hosted Checkout URL — the frontend redirects the browser there.
        `external_customer_id=str(org.id)` is how Polar links its own Customer record back to
        this org — every subsequent webhook for this subscription carries it on
        `subscription.customer.external_id`, so no separate "pending checkout" state needs to
        be tracked between session creation and webhook arrival (unlike a processor that only
        echoes back an opaque reference id)."""
        product_id = await self._resolve_product_id(org.id)

        async with Polar(
            access_token=self._require_access_token(), server=self.settings.polar_server
        ) as polar:
            checkout = await polar.checkouts.create_async(
                request=CheckoutCreate(
                    products=[product_id],
                    external_customer_id=str(org.id),
                    customer_email=user_email,
                    # The free 7 days already happened before this checkout ever ran — see
                    # app/core/entitlements.py's no-card trial, which starts at signup with no
                    # Polar involvement at all. allow_trial=False makes Checkout charge
                    # immediately regardless of whether a trial is still configured on the
                    # Polar Product itself (docs/billing/BILLING_ARCHITECTURE.md's Setup step
                    # 2) — belt-and-suspenders against ever granting a second, stacked trial.
                    allow_trial=False,
                    success_url=self.settings.billing_checkout_success_url,
                )
            )
        if checkout.url is None:
            raise ValidationError("Polar did not return a Checkout URL.")
        return checkout.url

    async def create_portal_session(self, *, org_id: uuid.UUID) -> str:
        """Returns a Polar-hosted Customer Portal URL — self-serve cancel / update card / view
        invoices. Requires an existing subscription (there's nothing to manage otherwise)."""
        subscription = await self.subscriptions.get_by_org(org_id)
        if subscription is None:
            raise NotFoundError("This organization has no billing account yet.")

        async with Polar(
            access_token=self._require_access_token(), server=self.settings.polar_server
        ) as polar:
            customer_session = await polar.customer_sessions.create_async(
                request=CustomerSessionCustomerExternalIDCreate(
                    external_customer_id=str(org_id),
                    return_url=self.settings.billing_portal_return_url,
                )
            )
        return customer_session.customer_portal_url

    async def handle_webhook_event(self, *, payload: bytes, headers: dict[str, str]) -> None:
        """Verifies the webhook signature (Standard Webhooks spec, via the SDK's own
        `validate_event`), then syncs `subscriptions` for every subscription-lifecycle event
        (see `_SUBSCRIPTION_PAYLOAD_TYPES` above). Every other event type Polar sends
        (checkout.*, customer.*, order.*, ...) is logged and ignored — this platform's
        entitlement logic depends only on subscription status, not on order/checkout
        bookkeeping Polar already owns."""
        webhook_secret = self.settings.polar_webhook_secret
        if webhook_secret is None:
            raise BillingNotConfigured("POLAR_WEBHOOK_SECRET is not set.")

        try:
            event = validate_event(payload, headers, webhook_secret.get_secret_value())
        except WebhookVerificationError as exc:
            raise ValidationError(f"Invalid Polar webhook signature: {exc}") from exc
        except WebhookUnknownTypeError as exc:
            # A real, signed event of a type this SDK version doesn't know about yet — safe
            # to ignore (see the "every other event type" note above), not an error.
            logger.info("billing.webhook_unknown_event_type", event_type=str(exc))
            return

        if isinstance(event, _SUBSCRIPTION_PAYLOAD_TYPES):
            await self._sync_subscription(event.data)
        else:
            logger.info("billing.webhook_event_ignored", event_type=type(event).__name__)

    async def _sync_subscription(self, polar_sub: PolarSubscription) -> None:
        org_id_raw = polar_sub.customer.external_id
        if not org_id_raw:
            # A subscription whose Customer was never linked to an org via
            # external_customer_id — cannot happen through this platform's own
            # create_checkout_session (it always sets it), but a subscription created
            # directly in the Polar Dashboard (e.g. manual test/comp account) would hit this.
            # Nothing to sync to; log and skip rather than guess.
            logger.warning(
                "billing.subscription_event_missing_external_customer_id",
                polar_subscription_id=polar_sub.id,
            )
            return

        subscription = await self.subscriptions.get_by_polar_subscription_id(polar_sub.id)
        is_new = subscription is None
        if subscription is None:
            subscription = Subscription(
                org_id=uuid.UUID(org_id_raw),
                polar_customer_id=polar_sub.customer_id,
                polar_subscription_id=polar_sub.id,
                polar_product_id=polar_sub.product_id,
                status=_parse_status(polar_sub.status.value),
            )
            self.session.add(subscription)

        subscription.status = _parse_status(polar_sub.status.value)
        subscription.polar_product_id = polar_sub.product_id
        subscription.trial_ends_at = polar_sub.trial_end
        subscription.current_period_end = polar_sub.current_period_end
        subscription.canceled_at = polar_sub.canceled_at
        await self.session.flush()

        if is_new:
            self.session.add(
                AuditLog(
                    org_id=subscription.org_id,
                    actor_user_id=None,
                    action="billing.subscription_started",
                    target=polar_sub.id,
                )
            )
            await self.session.flush()
        logger.info(
            "billing.subscription_synced",
            org_id=str(subscription.org_id),
            status=subscription.status.value,
        )

    async def get_pricing_tiers(self) -> list[TierStatus]:
        """Live "spots left" per tier for the public landing page — see app/core/pricing.py
        and GET /api/v1/billing/pricing-tiers. Read-only, no Polar call: counts this
        platform's own `subscriptions` rows, the same counter `_resolve_product_id` uses to
        assign a tier at checkout time, so the two are always in sync."""
        count = await self.subscriptions.count_all()
        return tier_statuses(count)

    async def _resolve_product_id(self, org_id: uuid.UUID) -> str:
        """Which Polar Product a checkout session should use — codeless tiered pricing, see
        app/core/pricing.py. An org that already has a subscription row (even canceled) keeps
        the product it originally checked out into, so its price is permanent and re-checkout
        never re-counts its own row against itself. A brand-new org is assigned a tier purely
        by how many organizations have ever checked out before it — no discount code, nothing
        the customer enters."""
        existing = await self.subscriptions.get_by_org(org_id)
        if existing is not None:
            return existing.polar_product_id
        count = await self.subscriptions.count_all()
        return self._require_tier_product_id(tier_for_count(count))

    def _require_tier_product_id(self, tier: PricingTier) -> str:
        product_id = {
            "founding": self.settings.polar_product_id_tier1,
            "early": self.settings.polar_product_id_tier2,
            "standard": self.settings.polar_product_id,
        }[tier.key]
        if product_id is None:
            raise BillingNotConfigured(
                f"No Polar Product configured for the '{tier.key}' pricing tier."
            )
        return product_id

    def _require_access_token(self) -> str:
        if self.settings.polar_access_token is None:
            raise BillingNotConfigured("POLAR_ACCESS_TOKEN is not set.")
        return self.settings.polar_access_token.get_secret_value()


def _parse_status(raw: str) -> SubscriptionStatus:
    try:
        return SubscriptionStatus(raw)
    except ValueError:
        # A Polar status this platform doesn't distinguish yet (e.g. `paused`, `unpaid`,
        # `incomplete_expired`) — treated conservatively as CANCELED (not entitled) rather
        # than crashing the webhook handler. See app/models/billing.py's SubscriptionStatus
        # docstring.
        logger.warning("billing.unrecognized_polar_status", raw_status=raw)
        return SubscriptionStatus.CANCELED
