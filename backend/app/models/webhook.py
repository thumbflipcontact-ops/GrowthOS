"""Outbound webhook delivery — see app/core/webhooks/dispatcher.py (the only place
`webhook_deliveries` rows are created or updated) and docs/api/API_DESIGN.md's public-API
section.

Deliberately independent of app/models/event.py's DomainEvent.dispatched_at, which is already
owned by app/core/dispatcher.py's agent-subscription consumer — two independent consumers of
the same `domain_events` outbox racing to set/read one shared "have I handled this" column
would break one or the other. `webhook_deliveries` is this consumer's own idempotency/retry
ledger: one row per (subscription, domain_event) pair, enforced by a unique constraint so
re-running the dispatcher never double-delivers.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin, pg_enum


class WebhookSubscription(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "webhook_subscriptions"
    __table_args__ = (Index("idx_webhook_subscriptions_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    created_by_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    target_url: Mapped[str] = mapped_column(nullable=False)
    # e.g. ["conversation.discovered"] — the external event name(s) this subscription wants.
    # Mirrors knowledge_items.tags' ARRAY(Text) shape.
    event_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    # HMAC signing secret for X-Threadly-Signature — shown to the caller once, at creation,
    # same "secret shown once" pattern as the API key itself.
    secret: Mapped[str] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookDeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class WebhookDelivery(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "webhook_subscription_id", "domain_event_id", name="uq_webhook_delivery_once_per_event"
        ),
        Index(
            "idx_webhook_deliveries_pending",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    webhook_subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    domain_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domain_events.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[WebhookDeliveryStatus] = mapped_column(
        pg_enum(WebhookDeliveryStatus, "webhook_delivery_status"),
        nullable=False,
        default=WebhookDeliveryStatus.PENDING,
        server_default=text("'pending'"),
    )
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_response_status: Mapped[int | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
