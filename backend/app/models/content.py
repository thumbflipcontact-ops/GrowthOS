"""The human-approval gate. See ARCHITECTURE.md §8.

Populated for real by Content Agent (Phase 2B, see
docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md) — always as `draft`, never advanced by
any agent code; ContentApprovalService (the actual state-machine enforcement moving
`draft`/`pending_review` on to `approved`/`rejected`/`published`) is still out of scope as
Phase 2C business logic. The `version` concurrency-guard column and `review_fields_consistent`
constraint have been in place since Phase 1, ahead of that service being built.
`confidence`/`reasoning`/`evidence` were added alongside Content Agent — see below.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin, pg_enum


class ContentItemStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class ContentItem(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "content_items"
    __table_args__ = (
        Index("idx_content_items_project_status", "project_id", "status"),
        CheckConstraint(
            "(reviewed_by_user_id is null) = (reviewed_at is null)",
            name="review_fields_consistent",
        ),
        CheckConstraint("confidence between 0 and 1", name="content_items_confidence_check"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # `type` is TEXT, not a native enum — plugin-contributed content types, validated at the
    # application layer against plugin_catalog. See docs/decisions/0008.
    type: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[ContentItemStatus] = mapped_column(
        pg_enum(ContentItemStatus, "content_item_status"),
        nullable=False,
        default=ContentItemStatus.DRAFT,
        server_default=text("'draft'"),
    )
    body: Mapped[str] = mapped_column(nullable=False)
    target_platform: Mapped[str | None] = mapped_column(nullable=True)
    target_ref: Mapped[str | None] = mapped_column(nullable=True)
    knowledge_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_items.id", ondelete="SET NULL"), nullable=True
    )
    created_by_agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_error: Mapped[str | None] = mapped_column(nullable=True)
    # The drafting agent's own self-assessment — added alongside Content Agent (Phase 2B).
    # `confidence` mirrors knowledge_items.confidence's shape (0-1), but means "how good the
    # agent judges its own draft to be," not a search-relevance score. `evidence` is a JSON
    # array of short quotes/citations from the source knowledge_item, never free-form prose,
    # so a human reviewer (Phase 2C) can scan it quickly.
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.0"), server_default=text("0.0")
    )
    reasoning: Mapped[str | None] = mapped_column(nullable=True)
    evidence: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Optimistic concurrency guard on the approve/reject transition — see
    # docs/reviews/DESIGN_REVIEW.md §3.2 and docs/architecture/LOCKED_DECISIONS.md L12.
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default=text("1"))
