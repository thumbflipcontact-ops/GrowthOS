"""The domain event outbox agents communicate through. See ARCHITECTURE.md §7 and
docs/decisions/0006-event-driven-agent-communication.md.

Every row is written in the SAME transaction as the fact it describes (the transactional
outbox pattern) — see app/core/events.py's EventPublisher, which is the only code that
should construct these rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class DomainEvent(UUIDPkMixin, Base):
    __tablename__ = "domain_events"
    __table_args__ = (
        Index(
            "idx_domain_events_undispatched",
            "project_id",
            postgresql_where="dispatched_at is null",
        ),
        Index("idx_domain_events_project_type", "project_id", "event_type"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
