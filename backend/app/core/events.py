"""The transactional outbox publisher. See ARCHITECTURE.md §7 and
docs/decisions/0006-event-driven-agent-communication.md.

`EventPublisher.publish` only ever adds the row to the current session and flushes — it
never commits. The caller (a service method, an agent's run()) is responsible for the
transaction boundary, so that a domain_events row is written in the exact same transaction
as the fact it describes. Calling publish() and committing separately from the row it
describes defeats the entire point of the outbox pattern — don't.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import DomainEvent


class EventPublisher:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def publish(
        self, *, project_id: uuid.UUID, event_type: str, payload: dict
    ) -> DomainEvent:
        event = DomainEvent(project_id=project_id, event_type=event_type, payload=payload)
        self.session.add(event)
        await self.session.flush()
        return event
