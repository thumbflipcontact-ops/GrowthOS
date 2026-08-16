"""Identity & tenancy — organizations, users, memberships. Mirrors database/schema.sql
"Identity & tenancy" section. See ARCHITECTURE.md §2 (multi-tenancy) and
docs/decisions/0001-multi-tenancy.md.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin, pg_enum

if TYPE_CHECKING:
    from app.models.project import Project


class Organization(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(nullable=False)
    slug: Mapped[str] = mapped_column(nullable=False, unique=True)
    # Manual, permanent entitlement override — see app/core/entitlements.py. Set directly in
    # the database for comped accounts (no admin UI yet, since there's exactly one use case so
    # far); once true, is_org_entitled() short-circuits to True regardless of what happens to
    # any subscription row afterward, so it survives a real Polar subscription later expiring,
    # failing, or getting canceled.
    is_comped: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )

    memberships: Mapped[list[Membership]] = relationship(back_populates="organization")
    projects: Mapped[list[Project]] = relationship(back_populates="organization")  # noqa: F821


class User(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(nullable=False, unique=True)
    name: Mapped[str] = mapped_column(nullable=False)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    # Set on both login (AuthService.authenticate) and signup (AuthService.register) — a new
    # account issues a session exactly like a login does. Read by app/core/agent_lifecycle.py's
    # inactivity sweep; nullable only because existing rows predate this column (migration
    # e4f6a8b0c2d3 backfills them to created_at), never expected to be NULL going forward.
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")


class MembershipRole(str, enum.Enum):
    OWNER = "owner"
    MEMBER = "member"


class Membership(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id"),)

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MembershipRole] = mapped_column(
        pg_enum(MembershipRole, "membership_role"),
        nullable=False,
        default=MembershipRole.OWNER,
        server_default=text("'owner'"),
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")
