"""Repository for the domain_events outbox. See ARCHITECTURE.md §7.

Deliberately narrow: creation goes through app/core/events.py's EventPublisher (which
enforces the transactional-outbox rule — an event is always written in the same transaction
as the fact it describes), not through this repository directly. This repository is for the
dispatcher's read/update-side of the outbox.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.event import DomainEvent
from app.repositories.base import Repository


class DomainEventRepository(Repository[DomainEvent]):
    model = DomainEvent

    async def list_undispatched(self, *, limit: int = 100) -> list[DomainEvent]:
        result = await self.session.execute(
            select(DomainEvent)
            .where(DomainEvent.dispatched_at.is_(None))
            .order_by(DomainEvent.occurred_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_dispatched(self, event_id: uuid.UUID) -> None:
        event = await self.get(event_id)
        if event is not None:
            event.dispatched_at = datetime.now(UTC)
            await self.session.flush()
