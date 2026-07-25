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
        `enqueue(agent_key, event)` per matching subscriber, then marks the event
        dispatched. Commits once at the end — if this crashes partway through, the
        undispatched rows already marked are safely skipped next cycle and the rest are
        simply retried; no event is ever lost (see database/schema.sql's domain_events
        note)."""
        pending = await self.events.list_undispatched(limit=limit)
        for event in pending:
            for agent_key in self.registry.subscribers_for(event.event_type, event.payload):
                await enqueue(agent_key, event)
            event.dispatched_at = datetime.now(UTC)
        await self.session.commit()
        return len(pending)
