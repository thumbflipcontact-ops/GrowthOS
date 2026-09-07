"""Email verification tokens — see app/services/email_verification_service.py (the only
place one is created or consumed) and app/core/api_keys.py, whose hashed-secret-token shape
this mirrors (same shape as app/models/password_reset.py's PasswordResetToken).

Like PasswordResetToken, user_id is ON DELETE CASCADE — a verification token has no reason to
outlive the user it belongs to.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin


class EmailVerificationToken(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "email_verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Nullable timestamp = still valid — same idiom as ApiKey.revoked_at.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
