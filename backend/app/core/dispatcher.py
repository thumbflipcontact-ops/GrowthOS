"""The event dispatcher's core logic. See ARCHITECTURE.md §7.

Deliberately separated from app/jobs/events.py's Arq periodic-job wrapper: this class does
"read undispatched events, find subscribers, hand off, mark dispatched" as plain
async/await, taking an injected `enqueue` callback rather than talking to Arq/Redis
directly — so the dispatch logic itself is unit-testable without a running Arq worker or a
real Redis. The Arq job is a thin adapter around this.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subscriptions import SubscriptionRegistry
from app.models.event import DomainEvent
from app.repositories.event_repository import DomainEventRepository

EnqueueFn = Callable[[str, DomainEvent], Awaitable[None]]


class EventDispatcher:
    def __init__(self, session: AsyncSession, registry: SubscriptionRegistry) -> None:
        self.session = session
        self.registry = registry
        self.events = DomainEventRepository(session)

    async def dispatch_pending(self, enqueue: EnqueueFn, *, limit: int = 100) -> int:
        """Processes up to `limit` undispatched events: for each, enqueues one call to
        `enqueue(agent_key, event)` per matching subscriber, then marks the event dispatched
        and commits — per event, not once for the whole batch (see
        docs/reviews/PRODUCTION_READINESS_REVIEW.md R1). Committing per event narrows the
        crash window to a single event: if this raises partway through (a Redis error, a
        crash), every event already committed as dispatched stays that way, and only the
        event that was mid-flight (plus anything after it in this batch) is left undispatched
        for the next cycle to pick up. Combined with `enqueue`'s own deterministic job id
        (see app/jobs/events.py), a re-dispatched event's re-enqueue is a no-op for any
        subscriber job still queued/running — no event is ever lost, and re-delivery is now
        also narrow and largely idempotent, instead of re-delivering the whole batch every
        time."""
        pending = await self.events.list_undispatched(limit=limit)
        for event in pending:
            for agent_key in self.registry.subscribers_for(event.event_type, event.payload):
                await enqueue(agent_key, event)
            event.dispatched_at = datetime.now(UTC)
            await self.session.commit()
        return len(pending)
