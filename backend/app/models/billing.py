"""Subscriptions — org-level billing state, mirrored from Polar. See
docs/billing/BILLING_ARCHITECTURE.md and ARCHITECTURE.md §2 (multi-tenancy).

Polar is the source of truth for a subscription's lifecycle; this table is a read-optimized
mirror kept in sync via webhook events (app/services/billing_service.py), never computed or
guessed locally — `status` is always whatever Polar's own subscription object last reported.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin, pg_enum

if TYPE_CHECKING:
    from app.models.identity import Organization


class SubscriptionStatus(str, enum.Enum):
    """Mirrors the subset of Polar's own `Subscription.status` values this platform's
    entitlement check (app/core/entitlements.py) actually distinguishes between — not every
    Polar status (e.g. `paused`, `unpaid`, `incomplete_expired`) has a distinct meaning here
    yet; those map to the closest equivalent below (CANCELED — see
    app/services/billing_service.py's `_parse_status`) rather than growing this enum ahead of
    a real need."""

    INCOMPLETE = "incomplete"  # created, first payment (e.g. 3DS) not yet confirmed
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"  # a renewal charge failed; Polar is retrying — not yet entitled
    CANCELED = "canceled"


# Exactly the statuses app/core/entitlements.py treats as "this org may use paid features" —
# a trial and a paid, current subscription are both entitled; everything else is not. Kept
# next to the enum it's derived from so the two can never silently drift apart.
ENTITLED_STATUSES = frozenset({SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE})


class Subscription(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    # One row per org for launch (docs/billing/BILLING_ARCHITECTURE.md's "why one plan, not
    # tiers" applies here too: modeling subscription *history* per org is real complexity
    # this MVP doesn't need yet — a canceled-then-resubscribed org updates its one row rather
    # than gaining a second). Revisit if/when that history is genuinely needed.
    __table_args__ = (UniqueConstraint("org_id"), UniqueConstraint("polar_subscription_id"))

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    polar_customer_id: Mapped[str] = mapped_column(nullable=False)
    polar_subscription_id: Mapped[str] = mapped_column(nullable=False)
    polar_product_id: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        pg_enum(SubscriptionStatus, "subscription_status"), nullable=False
    )
    # DateTime(timezone=True) explicit, not left to type inference — matches the convention
    # every other nullable timestamp column in this codebase follows (e.g.
    # PluginConnection.token_expires_at); without it SQLAlchemy compiles bind parameters as
    # naive TIMESTAMP, which asyncpg rejects outright for the tz-aware datetimes this table
    # always receives (Polar's API returns tz-aware timestamps).
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship()

    @property
    def is_entitled(self) -> bool:
        return self.status in ENTITLED_STATUSES
