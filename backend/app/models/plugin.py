"""Plugin catalog and connections. See docs/plugins/PLUGIN_ARCHITECTURE.md and
docs/database/SCHEMA.md's plugin_catalog / plugin_connections notes.

plugin_capability is a core-owned closed enum (the four capability Protocols) — deliberately
NOT the same kind of thing as content_items.type, which is plugin-contributed text. See
database/schema.sql's top-of-file convention note and
docs/decisions/0008-plugin-contributed-content-types.md.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, LargeBinary, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin, pg_enum


class PluginCapability(str, enum.Enum):
    SEARCHABLE = "searchable"
    PUBLISHABLE = "publishable"
    WEBHOOK_RECEIVABLE = "webhook_receivable"
    METRICS_QUERYABLE = "metrics_queryable"


# Shared enum type object so plugin_connections.capabilities_enabled and
# plugin_catalog.capabilities reference the identical Postgres type "plugin_capability"
# rather than each auto-creating their own.
_plugin_capability_enum = pg_enum(PluginCapability, "plugin_capability")


class PluginConnectionStatus(str, enum.Enum):
    CONNECTED = "connected"
    ERROR = "error"
    DISCONNECTED = "disconnected"
    # See docs/auth/OAUTH2_ARCHITECTURE.md §2 — distinct from ERROR: a refresh that fails
    # permanently (invalid_grant — the refresh token itself is dead) needs a human to
    # reconnect; a transient failure (network blip) stays CONNECTED and is retried, never
    # surfaced as EXPIRED.
    EXPIRED = "expired"


class PluginCatalogEntry(CreatedAtMixin, Base):
    """Mirrors the in-process plugin manifest scan performed at startup — refreshed
    wholesale on each process start (see docs/plugins/PLUGIN_ARCHITECTURE.md §Discovery),
    never hand-edited. `created_at` here is repurposed as "first seen"; `refreshed_at`
    tracks the most recent scan that confirmed this plugin is still installed."""

    __tablename__ = "plugin_catalog"

    plugin_key: Mapped[str] = mapped_column(primary_key=True)
    interface_version: Mapped[str] = mapped_column(nullable=False)
    capabilities: Mapped[list[PluginCapability]] = mapped_column(
        ARRAY(_plugin_capability_enum),
        nullable=False,
        default=list,
        server_default=text("'{}'::plugin_capability[]"),
    )
    content_types: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    config_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    auth_type: Mapped[str] = mapped_column(nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PluginConnection(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "plugin_connections"
    __table_args__ = (UniqueConstraint("project_id", "plugin_key", "label"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Validated at the application layer against plugin_catalog, not a hard FK — the catalog
    # is rebuilt at every process start. See docs/database/SCHEMA.md.
    plugin_key: Mapped[str] = mapped_column(nullable=False)
    # Disambiguates multiple connections to the same plugin within one project (two Reddit
    # accounts, two Slack workspaces) — see docs/auth/OAUTH2_ARCHITECTURE.md §2. Defaults
    # "default" so the common one-connection-per-plugin case needs no special handling.
    label: Mapped[str] = mapped_column(
        nullable=False, default="default", server_default=text("'default'")
    )
    capabilities_enabled: Mapped[list[PluginCapability]] = mapped_column(
        ARRAY(_plugin_capability_enum),
        nullable=False,
        default=list,
        server_default=text("'{}'::plugin_capability[]"),
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    credentials_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    credential_data_key_wrapped: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[PluginConnectionStatus] = mapped_column(
        pg_enum(PluginConnectionStatus, "plugin_connection_status"),
        nullable=False,
        default=PluginConnectionStatus.DISCONNECTED,
        server_default=text("'disconnected'"),
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Plaintext, deliberately — neither is a credential. expires_at drives the refresh sweep's
    # query without decrypting anything; granted_scopes lets a status API answer "what did
    # this connection actually authorize" without an encrypt/decrypt round trip. The actual
    # access/refresh tokens live exclusively in credentials_encrypted (ADR 0010). See
    # docs/auth/OAUTH2_ARCHITECTURE.md §2.
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    granted_scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
