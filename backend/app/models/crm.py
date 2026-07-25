"""CRM-lite: companies, contacts, competitors. See docs/database/SCHEMA.md.

Tables only in Phase 1 — Customer Finder / Competitor Watch (the agents that would populate
these) are explicitly out of Phase 1 scope, see ROADMAP.md.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin, pg_enum


class Company(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("project_id", "domain"),
        CheckConstraint("icp_score between 0 and 1", name="companies_icp_score_check"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(nullable=False)
    domain: Mapped[str | None] = mapped_column(nullable=True)
    industry: Mapped[str | None] = mapped_column(nullable=True)
    size_bucket: Mapped[str | None] = mapped_column(nullable=True)
    icp_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    source: Mapped[str | None] = mapped_column(nullable=True)


class ContactStatus(str, enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    REPLIED = "replied"
    QUALIFIED = "qualified"
    CUSTOMER = "customer"
    LOST = "lost"


class Contact(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "contacts"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str | None] = mapped_column(nullable=True)
    platform: Mapped[str | None] = mapped_column(nullable=True)
    profile_url: Mapped[str | None] = mapped_column(nullable=True)
    role: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[ContactStatus] = mapped_column(
        pg_enum(ContactStatus, "contact_status"),
        nullable=False,
        default=ContactStatus.NEW,
        server_default=text("'new'"),
    )


class Competitor(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("project_id", "domain"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(nullable=False)
    domain: Mapped[str | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(nullable=True)


class CompetitorObservation(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "competitor_observations"

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    type: Mapped[str] = mapped_column(nullable=False)
    summary: Mapped[str] = mapped_column(nullable=False)
    source_url: Mapped[str | None] = mapped_column(nullable=True)
