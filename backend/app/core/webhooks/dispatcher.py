"""The outbound-webhook sweep's core logic — see app/jobs/webhooks.py for the Arq periodic-job
wrapper. Deliberately separated the same way app/core/oauth/refresh.py's OAuthRefreshSweep is
from app/jobs/oauth_refresh.py, so this runs and is tested as plain async/await against a real
session, without a running Arq worker.

A second, independent consumer of the domain_events outbox (app/core/events.py) alongside the
existing agent-subscription dispatcher (app/core/dispatcher.py) — deliberately NOT sharing that
dispatcher's domain_events.dispatched_at column, which is already owned by it. This dispatcher
tracks its own progress via webhook_deliveries, one row per (subscription, domain_event) pair,
enforced by a unique constraint so re-running this sweep never double-delivers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.webhooks.client import WebhookHttpClient
from app.core.webhooks.errors import WebhookDeliveryFailed
from app.core.webhooks.signing import sign_payload
from app.models.event import DomainEvent
from app.models.webhook import WebhookDelivery, WebhookDeliveryStatus, WebhookSubscription
from app.repositories.webhook_repository import (
    WebhookDeliveryRepository,
    WebhookSubscriptionRepository,
)

logger = structlog.get_logger()

# External event name -> internal domain_events.event_type it's derived from. The only
# mapping today — see plan's "explicitly out of scope" section for why this stays a 1-entry
# dict rather than a general registry until a second event type is actually needed.
EXTERNAL_TO_INTERNAL_EVENT_TYPE = {"conversation.discovered": "knowledge_item.created"}
_INTERNAL_TO_EXTERNAL_EVENT_TYPE = {v: k for k, v in EXTERNAL_TO_INTERNAL_EVENT_TYPE.items()}

# Exponential backoff between delivery attempts; terminal `failed` once exhausted.
_BACKOFF_SCHEDULE = [
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(hours=1),
    timedelta(hours=6),
]
_MAX_ATTEMPTS = len(_BACKOFF_SCHEDULE)


class WebhookDispatcher:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.subscriptions = WebhookSubscriptionRepository(session)
        self.deliveries = WebhookDeliveryRepository(session)
        self.client = WebhookHttpClient()

    async def run(self, *, now: datetime | None = None) -> int:
        """Creates pending delivery rows for any newly-matching domain_events, then attempts
        every due delivery. Returns the count of delivery attempts made this cycle (not the
        count of new rows created)."""
        now = now or datetime.now(UTC)
        await self._create_pending_deliveries(now)
        attempted = await self._attempt_due_deliveries(now)
        await self.session.commit()
        return attempted

    async def _create_pending_deliveries(self, now: datetime) -> None:
        for subscription in await self.subscriptions.list_all_enabled():
            for external_type in subscription.event_types:
                internal_type = EXTERNAL_TO_INTERNAL_EVENT_TYPE.get(external_type)
                if internal_type is None:
                    continue  # an event_type this deployment doesn't know how to map yet
                events = await self.deliveries.list_undelivered_domain_events(
                    subscription_id=subscription.id,
                    project_id=subscription.project_id,
                    event_type=internal_type,
                )
                for event in events:
                    self.session.add(
                        WebhookDelivery(
                            webhook_subscription_id=subscription.id,
                            domain_event_id=event.id,
                            next_attempt_at=now,
                        )
                    )
        await self.session.flush()

    async def _attempt_due_deliveries(self, now: datetime) -> int:
        due = await self.deliveries.list_due(now=now)
        for delivery in due:
            await self._attempt_one(delivery, now=now)
        return len(due)

    async def _attempt_one(self, delivery: WebhookDelivery, *, now: datetime) -> None:
        subscription = await self.session.get(WebhookSubscription, delivery.webhook_subscription_id)
        event = await self.session.get(DomainEvent, delivery.domain_event_id)
        if subscription is None or event is None:
            # Referenced row disappeared (e.g. the subscription was hard-deleted some other
            # way) — nothing sensible to retry.
            delivery.status = WebhookDeliveryStatus.FAILED
            delivery.last_error = "subscription or domain event no longer exists"
            return

        external_type = _INTERNAL_TO_EXTERNAL_EVENT_TYPE.get(event.event_type, event.event_type)
        body = json.dumps(
            {
                "event": external_type,
                "delivery_id": str(delivery.id),
                "occurred_at": event.occurred_at.isoformat(),
                "data": event.payload,
            }
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Threadly-Event": external_type,
            "X-Threadly-Delivery": str(delivery.id),
            "X-Threadly-Signature": f"sha256={sign_payload(subscription.secret, body)}",
        }

        delivery.attempt_count += 1
        try:
            status_code = await self.client.send(
                url=subscription.target_url, headers=headers, body=body
            )
        except WebhookDeliveryFailed as exc:
            delivery.last_error = str(exc)
            if delivery.attempt_count >= _MAX_ATTEMPTS:
                delivery.status = WebhookDeliveryStatus.FAILED
                logger.warning(
                    "webhook_dispatcher.delivery_failed_terminal",
                    delivery_id=str(delivery.id),
                    attempt_count=delivery.attempt_count,
                )
            else:
                delivery.next_attempt_at = now + _BACKOFF_SCHEDULE[delivery.attempt_count - 1]
            return

        delivery.status = WebhookDeliveryStatus.SUCCESS
        delivery.last_response_status = status_code
        delivery.delivered_at = now


__all__ = ["WebhookDispatcher"]
