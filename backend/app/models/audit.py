"""Security audit trail — separate from content_items' human-approval trail. See
docs/database/SCHEMA.md's audit_log note and docs/security/SECURITY.md.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin


class AuditLog(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("idx_audit_log_org_created", "org_id", "created_at"),)

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(nullable=False)
    target: Mapped[str | None] = mapped_column(nullable=True)
    # "metadata" is a reserved attribute name on SQLAlchemy's DeclarativeBase (Base.metadata
    # is the schema MetaData registry) — the Python attribute is `metadata_`, the actual
    # database column stays named "metadata" to match database/schema.sql exactly.
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
