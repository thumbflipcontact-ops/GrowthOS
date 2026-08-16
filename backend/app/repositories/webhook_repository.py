"""Repositories for outbound webhook delivery — see app/core/webhooks/dispatcher.py.

WebhookDeliveryRepository.list_undelivered_domain_events deliberately lives here, not on
DomainEventRepository (app/repositories/event_repository.py) — that repository's
list_undispatched is specific to the agent-subscription consumer's own dispatched_at column;
this is a webhook-delivery-ledger concern (what needs a webhook_deliveries row), a different
question against the same domain_events table. Keeping the join here avoids coupling the
generic event repository to a webhook-specific table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.event import DomainEvent
from app.models.webhook import WebhookDelivery, WebhookDeliveryStatus, WebhookSubscription
from app.repositories.base import Repository


class WebhookSubscriptionRepository(Repository[WebhookSubscription]):
    model = WebhookSubscription

    async def list_by_project(self, project_id: uuid.UUID) -> list[WebhookSubscription]:
        result = await self.session.execute(
            select(WebhookSubscription).where(WebhookSubscription.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get_scoped(
        self, project_id: uuid.UUID, subscription_id: uuid.UUID
    ) -> WebhookSubscription | None:
        result = await self.session.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.id == subscription_id,
                WebhookSubscription.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_all_enabled(self) -> list[WebhookSubscription]:
        """What app/core/webhooks/dispatcher.py polls every cycle — every currently-enabled
        subscription, across every project. Fine at today's scale (a handful of subscriptions
        total); revisit with a project_id-scoped variant only if that stops being true."""
        result = await self.session.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.enabled.is_(True), WebhookSubscription.revoked_at.is_(None)
            )
        )
        return list(result.scalars().all())


class WebhookDeliveryRepository(Repository[WebhookDelivery]):
    model = WebhookDelivery

    async def list_undelivered_domain_events(
        self,
        *,
        subscription_id: uuid.UUID,
        project_id: uuid.UUID,
        event_type: str,
        limit: int = 100,
    ) -> list[DomainEvent]:
        """DomainEvents matching (project_id, event_type) with no existing webhook_deliveries
        row for this subscription yet — what the dispatcher turns into new `pending` delivery
        rows each cycle. Backed by idx_domain_events_project_type; a NOT EXISTS subquery
        rather than a LEFT JOIN, matching this codebase's existing "not optimized
        speculatively" philosophy for dedup checks (see knowledge_repository.py's
        get_by_url)."""
        existing = select(WebhookDelivery.domain_event_id).where(
            WebhookDelivery.webhook_subscription_id == subscription_id
        )
        result = await self.session.execute(
            select(DomainEvent)
            .where(
                DomainEvent.project_id == project_id,
                DomainEvent.event_type == event_type,
                DomainEvent.id.not_in(existing),
            )
            .order_by(DomainEvent.occurred_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_due(self, *, now: datetime, limit: int = 100) -> list[WebhookDelivery]:
        result = await self.session.execute(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status == WebhookDeliveryStatus.PENDING,
                WebhookDelivery.next_attempt_at <= now,
            )
            .order_by(WebhookDelivery.next_attempt_at)
            .limit(limit)
        )
        return list(result.scalars().all())
