"""External identity-provider login (Google, ...) — links a `users` row to one provider
account, entirely separate from `plugin_connections` (which links a *project* to a
data-source/publishing plugin like Reddit). See app/services/google_oauth_service.py, the
only writer.

A user can exist with no row here at all (password-only) or exactly one row per provider
they've signed in with — never more than one per (provider, provider_user_id) pair, since
that pair is how a returning login is matched back to an account.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin


class OAuthIdentity(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "oauth_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # "google" today; a free-form string (not a closed enum), same reasoning as LtdCode.source
    # — a future provider (Apple, ...) adds rows under a new value, no migration required.
    provider: Mapped[str] = mapped_column(nullable=False)
    # The provider's own stable subject identifier (Google's "sub" claim) — never the email,
    # which a provider account can change; this is what a returning login is actually matched
    # against.
    provider_user_id: Mapped[str] = mapped_column(nullable=False)
