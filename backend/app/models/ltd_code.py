"""AppSumo-style lifetime-deal redemption codes — see app/services/ltd_redemption_service.py
(the only place one is created or redeemed) and Organization.is_ltd/max_projects.

Unlike EmailVerificationToken/PasswordResetToken, `code` is stored in plaintext, not hashed —
it isn't a session credential (redeeming one still requires supplying a real name/email/
password to create the account; knowing a code alone grants nothing), and an operator needs
to read codes back out directly to hand a batch to AppSumo — see
scripts/generate_ltd_codes.py.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin, pg_enum


class LtdCodeStatus(str, enum.Enum):
    UNREDEEMED = "unredeemed"
    REDEEMED = "redeemed"


class LtdCode(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "ltd_codes"

    code: Mapped[str] = mapped_column(nullable=False, unique=True)
    status: Mapped[LtdCodeStatus] = mapped_column(
        pg_enum(LtdCodeStatus, "ltd_code_status"),
        nullable=False,
        default=LtdCodeStatus.UNREDEEMED,
        server_default=text("'unredeemed'"),
    )
    # ON DELETE SET NULL, not CASCADE — a redeemed code's own record (which code redeemed
    # which org, when) is worth keeping for reconciliation against AppSumo even if the
    # organization itself is later deleted; only the link to it should go.
    redeemed_by_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
