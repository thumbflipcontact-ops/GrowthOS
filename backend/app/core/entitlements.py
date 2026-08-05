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

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import SubscriptionRequiredError
from app.repositories.billing_repository import SubscriptionRepository


async def is_org_entitled(session: AsyncSession, org_id: uuid.UUID) -> bool:
    """True if `org_id` has a subscription row whose Stripe-mirrored status is `trialing` or
    `active`. False for no subscription at all (never signed up for billing), `past_due`
    (a renewal charge failed), and `canceled` — none of those may consume paid, metered
    plugin capacity (external API calls this platform pays for per-use, e.g. X's pay-per-use
    pricing — see plugins/twitter/README.md)."""
    subscription = await SubscriptionRepository(session).get_by_org(org_id)
    return subscription is not None and subscription.is_entitled


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
