"""The knowledge base — institutional memory. See docs/knowledge-base/KNOWLEDGE_BASE.md.

Table only in Phase 1 — no agent populates this yet (Conversation Finder is explicitly out
of Phase 1 scope, see ROADMAP.md). The model exists because Alembic's schema must match
database/schema.sql in full.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin, pg_enum

EMBEDDING_DIM = 1536  # matches the OpenAI text-embedding-3 family — see docs/database/SCHEMA.md


class BuyingIntent(str, enum.Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class KnowledgeItem(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "knowledge_items"
    __table_args__ = (
        UniqueConstraint("project_id", "url"),
        CheckConstraint("confidence between 0 and 1", name="knowledge_items_confidence_check"),
        Index("idx_knowledge_items_project", "project_id"),
        Index("idx_knowledge_items_tags", "tags", postgresql_using="gin"),
        Index(
            "idx_knowledge_items_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(nullable=False)
    url: Mapped[str] = mapped_column(nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    problem: Mapped[str | None] = mapped_column(nullable=True)
    industry: Mapped[str | None] = mapped_column(nullable=True)
    product: Mapped[str | None] = mapped_column(nullable=True)
    pain_point: Mapped[str | None] = mapped_column(nullable=True)
    buying_intent: Mapped[BuyingIntent] = mapped_column(
        pg_enum(BuyingIntent, "buying_intent"),
        nullable=False,
        default=BuyingIntent.NONE,
        server_default=text("'none'"),
    )
    suggested_reply: Mapped[str | None] = mapped_column(nullable=True)
    suggested_article: Mapped[str | None] = mapped_column(nullable=True)
    suggested_product_idea: Mapped[str | None] = mapped_column(nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.0"), server_default=text("0.0")
    )
    outcome: Mapped[str | None] = mapped_column(nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
