from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class PortalSessionResponse(BaseModel):
    portal_url: str


class SubscriptionStatusResponse(BaseModel):
    """What the frontend dashboard renders — see app/api/v1/billing.py's GET .../status.
    `has_subscription=False` (every field after it null) is the normal state for an org that
    registered but hasn't completed Checkout yet, not an error."""

    has_subscription: bool
    status: str | None
    is_entitled: bool
    trial_ends_at: datetime | None
    current_period_end: datetime | None
