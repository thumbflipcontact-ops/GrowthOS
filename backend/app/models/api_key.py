"""Public-API keys — see app/api/deps.py's require_api_key_project (the only place a key is
verified) and app/services/api_key.py (the only place one is created/revoked).

Project-scoped, not org-scoped — every existing route is already project-scoped and there is
no "act across an org's projects" concept elsewhere in this codebase (see
docs/api/API_DESIGN.md: no cross-project query endpoint). One key per project keeps a leaked
key's blast radius to a single project.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin


class ApiKey(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("idx_api_keys_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Who a key-triggered content_items approve/reject gets attributed to (ContentItem's
    # review_fields_consistent CHECK constraint requires a real reviewed_by_user_id — see
    # app/services/api_key.py's docstring for why this can't just be null the way an
    # auto-disable sweep's actor_user_id can). SET NULL, not RESTRICT: deleting a user must
    # never be blocked by an unrelated API key row — a key whose creator was deleted is
    # instead explicitly rejected at the service boundary, not left to violate a constraint.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(nullable=False)
    key_hash: Mapped[str] = mapped_column(nullable=False, unique=True)
    # First 12 characters of the plaintext token, stored unhashed — lets a list view show
    # "which key is this" without ever being able to reconstruct the full secret.
    key_prefix: Mapped[str] = mapped_column(nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
