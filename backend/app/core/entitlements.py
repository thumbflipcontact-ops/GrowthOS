"""Subscription entitlement checks — see docs/billing/BILLING_ARCHITECTURE.md.

Deliberately Stripe-independent (only reads the `subscriptions` table `app/services/
billing_service.py` keeps in sync) so background job bodies can import this without pulling
in the Stripe SDK or any billing-orchestration code — the same layering as
`app/core/oauth/client.py` (talks to providers) vs. `plugins/*/client.py` (only ever consumes
a token it was handed). This module is also plugin-agnostic on purpose: it answers "does this
org have an active subscription or trial," full stop, never "does this org have an active
Twitter connection" — the same generic contract every plugin, not just Twitter, gets gated by,
including Reddit and LinkedIn once they're connected, with zero changes here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import SubscriptionRequiredError
from app.repositories.billing_repository import SubscriptionRepository
from app.repositories.organization_repository import OrganizationRepository

# How long a brand-new org is entitled without ever adding a card or completing Polar
# Checkout — see docs/billing/BILLING_ARCHITECTURE.md's "No-card trial". Computed from
# Organization.created_at rather than stored on its own column: no migration needed, and it
# can never drift out of sync with when the org actually signed up.
NO_CARD_TRIAL_DAYS = 7


async def is_org_entitled(session: AsyncSession, org_id: uuid.UUID) -> bool:
    """True if `org_id` has a subscription row whose Polar-mirrored status is `trialing` or
    `active`, OR has no subscription row yet but is still within its no-card trial window
    (NO_CARD_TRIAL_DAYS from Organization.created_at — see billing_service.py's
    create_checkout_session, which no longer asks Polar for its own trial on top of this).
    False for `past_due` (a renewal charge failed), `canceled`, and a no-card trial that has
    elapsed without the org ever completing Checkout — none of those may consume paid,
    metered plugin capacity (external API calls this platform pays for per-use, e.g. X's
    pay-per-use pricing — see plugins/twitter/README.md)."""
    subscription = await SubscriptionRepository(session).get_by_org(org_id)
    if subscription is not None:
        return subscription.is_entitled

    organization = await OrganizationRepository(session).get(org_id)
    if organization is None:
        return False
    return datetime.now(UTC) < no_card_trial_ends_at(organization.created_at)


def no_card_trial_ends_at(org_created_at: datetime) -> datetime:
    return org_created_at + timedelta(days=NO_CARD_TRIAL_DAYS)


async def require_org_entitled(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Same check as `is_org_entitled`, raising `SubscriptionRequiredError` (402) instead of
    returning a bool — for call sites (the FastAPI dependency in app/api/deps.py) that want
    the request to fail outright rather than branch on a bool themselves. Background job
    bodies call `is_org_entitled` directly instead, since a job has no HTTP response to
    return a 402 into — it logs and skips the work, see app/jobs/agent_runs.py."""
    if not await is_org_entitled(session, org_id):
        raise SubscriptionRequiredError(
            "This organization does not have an active subscription or trial.",
            details={"org_id": str(org_id)},
        )
