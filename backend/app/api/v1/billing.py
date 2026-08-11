"""Billing endpoints — see docs/billing/BILLING_ARCHITECTURE.md.

Org-scoped (checkout-session, portal-session) via `require_org_access`, the same dependency
`app/api/deps.py` already documents as "the org-scoped counterpart to require_project_access"
— billing is an org-level concern (like memberships), not a project-level one.

The webhook route is deliberately NOT org-scoped and NOT behind `get_current_user` — Polar
calls it directly with no session cookie, at one fixed URL (the same reasoning
app/api/v1/oauth.py's callback route documents for OAuth providers). Its own body is the only
authentication: a valid Polar signature over the raw request bytes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_settings_dep, require_org_access
from app.core.config import Settings
from app.core.entitlements import no_card_trial_ends_at
from app.models.identity import Organization, User
from app.repositories.billing_repository import SubscriptionRepository
from app.schemas.billing import (
    CheckoutSessionResponse,
    PortalSessionResponse,
    PricingTierResponse,
    PricingTiersResponse,
    SubscriptionStatusResponse,
)
from app.services.billing_service import BillingService

router = APIRouter(tags=["billing"])


@router.get("/billing/pricing-tiers", response_model=PricingTiersResponse)
async def get_pricing_tiers(
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> PricingTiersResponse:
    """Public, unauthenticated — the landing page's live "spots left" indicator (shown before
    signup, so there's no org/user to scope it to). No PII, just per-tier counts derived from
    app/core/pricing.py's pure math over BillingService.get_pricing_tiers()."""
    statuses = await BillingService(session, settings).get_pricing_tiers()
    return PricingTiersResponse(
        tiers=[
            PricingTierResponse(
                key=s.tier.key,
                label=s.tier.label,
                price_usd=s.tier.price_usd,
                capacity=s.tier.capacity,
                spots_taken=s.spots_taken,
                spots_left=s.spots_left,
                is_current=s.is_current,
                is_sold_out=s.is_sold_out,
            )
            for s in statuses
        ]
    )


@router.get("/orgs/{org_id}/billing/status", response_model=SubscriptionStatusResponse)
async def get_subscription_status(
    org: Organization = Depends(require_org_access),
    session: AsyncSession = Depends(get_db),
) -> SubscriptionStatusResponse:
    """Read-only — what the dashboard renders (trial countdown, "subscribe now", etc.). Never
    talks to Polar; reads the local mirror app/services/billing_service.py's webhook handler
    keeps in sync, the same source app/core/entitlements.py gates on.

    Checked first, same as is_org_entitled: a comped org (Organization.is_comped) short-
    circuits here too, so the dashboard never shows a "subscribe now" / "trial ended" /
    "update your card" prompt to an account that's actually permanently entitled regardless
    of what its real subscription row says."""
    if org.is_comped:
        return SubscriptionStatusResponse(
            has_subscription=False,
            status=None,
            is_entitled=True,
            trial_ends_at=None,
            current_period_end=None,
            no_card_trial_ends_at=None,
            is_comped=True,
        )

    subscription = await SubscriptionRepository(session).get_by_org(org.id)
    if subscription is None:
        # No Checkout completed yet — org is on its no-card trial (see
        # app/core/entitlements.py), which the dashboard needs to render a countdown for
        # (still running) or a "subscribe now" prompt (elapsed) — is_entitled distinguishes
        # the two.
        trial_ends_at = no_card_trial_ends_at(org.created_at)
        return SubscriptionStatusResponse(
            has_subscription=False,
            status=None,
            is_entitled=datetime.now(UTC) < trial_ends_at,
            trial_ends_at=None,
            current_period_end=None,
            no_card_trial_ends_at=trial_ends_at,
        )
    return SubscriptionStatusResponse(
        has_subscription=True,
        status=subscription.status.value,
        is_entitled=subscription.is_entitled,
        trial_ends_at=subscription.trial_ends_at,
        current_period_end=subscription.current_period_end,
        no_card_trial_ends_at=None,
    )


@router.post(
    "/orgs/{org_id}/billing/checkout-session",
    response_model=CheckoutSessionResponse,
    status_code=201,
)
async def create_checkout_session(
    org: Organization = Depends(require_org_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> CheckoutSessionResponse:
    """Returns a Polar Checkout URL for the frontend to redirect the browser to — starts the
    7-day trial once the customer completes it there. Safe to call again for an org that
    already has a subscription (e.g. after an abandoned checkout); Polar reuses the existing
    customer via `external_customer_id`."""
    url = await BillingService(session, settings).create_checkout_session(
        org=org, user_email=current_user.email
    )
    return CheckoutSessionResponse(checkout_url=url)


@router.post(
    "/orgs/{org_id}/billing/portal-session",
    response_model=PortalSessionResponse,
)
async def create_portal_session(
    org: Organization = Depends(require_org_access),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> PortalSessionResponse:
    """Returns a Polar Customer Portal URL — self-serve cancel / update card / view invoices.
    404s if this org has never completed a checkout (nothing to manage yet)."""
    url = await BillingService(session, settings).create_portal_session(org_id=org.id)
    return PortalSessionResponse(portal_url=url)


@router.post("/billing/webhook", status_code=204, response_model=None)
async def billing_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    """Polar's one fixed webhook endpoint. Reads the raw body (not a parsed Pydantic model —
    signature verification needs the exact bytes Polar signed) and every header (Standard
    Webhooks signs across a specific header set the SDK reads itself, not just one
    `X-...-Signature` header)."""
    payload = await request.body()
    await BillingService(session, settings).handle_webhook_event(
        payload=payload, headers=dict(request.headers)
    )
