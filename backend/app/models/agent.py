"""Agent configuration and execution audit trail. See docs/agents/AGENT_ARCHITECTURE.md.

agent_configs is mutable state (schedule/config you can change); agent_runs is an immutable
historical record — see docs/database/SCHEMA.md's split rationale.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin, pg_enum


class AgentConfig(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "agent_configs"
    __table_args__ = (UniqueConstraint("project_id", "agent_key"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_key: Mapped[str] = mapped_column(nullable=False)
    schedule_cron: Mapped[str | None] = mapped_column(nullable=True)
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))


class AgentRunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AgentRun(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "agent_runs"

    agent_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_configs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_key: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(
        pg_enum(AgentRunStatus, "agent_run_status"),
        nullable=False,
        default=AgentRunStatus.QUEUED,
        server_default=text("'queued'"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(nullable=True)
