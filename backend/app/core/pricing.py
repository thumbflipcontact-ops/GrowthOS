"""Codeless tiered launch pricing — see docs/billing/BILLING_ARCHITECTURE.md's "Tiered launch
pricing" section.

No discount codes, nothing customer-entered: which price an org pays is decided once, at its
first checkout, purely by counting how many organizations have ever created a subscription row
before it (see `BillingService._resolve_product_id`). This module only holds the tier
definitions and the pure counting math — it has no DB or Polar dependency, so it's trivial to
unit test in isolation. Polar-facing product selection lives in `billing_service.py`; the
public "spots left" read is exposed via `app/api/v1/billing.py`'s `GET /billing/pricing-tiers`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PricingTier:
    key: str
    label: str
    price_usd: int
    # None only on the final (standard) tier. Capacity is "how many MORE signups this tier
    # absorbs after every earlier tier has filled" (cumulative), not a total headcount.
    capacity: int | None


# First 5 organizations ever to check out get $9/month, the next 10 get $19/month, everyone
# after that pays $29/month — a product decision (see the pricing thread in
# docs/billing/BILLING_ARCHITECTURE.md), not something to re-tune casually: an org's tier is
# permanent once assigned (BillingService._resolve_product_id is sticky), so changing these
# numbers only affects organizations that haven't checked out yet.
PRICING_TIERS: tuple[PricingTier, ...] = (
    PricingTier(key="founding", label="Founding members", price_usd=9, capacity=5),
    PricingTier(key="early", label="Early adopters", price_usd=19, capacity=10),
    PricingTier(key="standard", label="Standard", price_usd=29, capacity=None),
)


def tier_for_count(signup_count: int) -> PricingTier:
    """Which tier the (signup_count + 1)-th organization to ever check out lands in.
    `signup_count` is the number of organizations that already have a subscription row."""
    threshold = 0
    for tier in PRICING_TIERS:
        if tier.capacity is None:
            return tier
        threshold += tier.capacity
        if signup_count < threshold:
            return tier
    return PRICING_TIERS[-1]


@dataclass(frozen=True)
class TierStatus:
    tier: PricingTier
    spots_taken: int
    spots_left: int | None
    is_current: bool  # the tier a new signup would land in right now
    is_sold_out: bool


def tier_statuses(signup_count: int) -> list[TierStatus]:
    """Per-tier occupancy for the public "spots left" display — see `get_pricing_tiers`."""
    statuses: list[TierStatus] = []
    remaining = signup_count
    current_found = False
    for tier in PRICING_TIERS:
        if tier.capacity is None:
            statuses.append(
                TierStatus(
                    tier=tier,
                    spots_taken=max(remaining, 0) if not current_found else 0,
                    spots_left=None,
                    is_current=not current_found,
                    is_sold_out=False,
                )
            )
            break
        taken = min(max(remaining, 0), tier.capacity)
        sold_out = remaining >= tier.capacity
        is_current = not current_found and not sold_out
        statuses.append(
            TierStatus(
                tier=tier,
                spots_taken=taken,
                spots_left=tier.capacity - taken,
                is_current=is_current,
                is_sold_out=sold_out,
            )
        )
        if is_current:
            current_found = True
        remaining -= tier.capacity
    return statuses
