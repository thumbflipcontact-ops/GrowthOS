"""The materialized "what should I do today" view. See docs/knowledge-base/KNOWLEDGE_BASE.md.

Table only in Phase 1 — assembled by the orchestrator, which is out of Phase 1 scope as
business logic (see ROADMAP.md).
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin


class DailyBrief(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "daily_briefs"
    __table_args__ = (UniqueConstraint("project_id", "brief_date"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    brief_date: Mapped[date] = mapped_column(Date, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
