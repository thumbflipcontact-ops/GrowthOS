from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class PortalSessionResponse(BaseModel):
    portal_url: str


class SubscriptionStatusResponse(BaseModel):
    """What the frontend dashboard renders — see app/api/v1/billing.py's GET .../status.
    `has_subscription=False` is the normal state for an org that registered but hasn't
    completed Checkout yet, not an error — `no_card_trial_ends_at` is set whenever
    `has_subscription` is false (whether that trial is still running or already elapsed;
    `is_entitled` distinguishes the two), and null once the org has an actual subscription."""

    has_subscription: bool
    status: str | None
    is_entitled: bool
    trial_ends_at: datetime | None
    current_period_end: datetime | None
    no_card_trial_ends_at: datetime | None


class PricingTierResponse(BaseModel):
    """One row of the public "spots left" pricing display — see app/core/pricing.py and
    GET /api/v1/billing/pricing-tiers."""

    key: str
    label: str
    price_usd: int
    capacity: int | None
    spots_taken: int
    spots_left: int | None
    is_current: bool
    is_sold_out: bool


class PricingTiersResponse(BaseModel):
    tiers: list[PricingTierResponse]
