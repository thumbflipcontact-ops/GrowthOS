"""add content_items.notified_at

Revision ID: c7e9f1a3b5d7
Revises: b4d6f8a0c2e4
Create Date: 2026-09-07 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7e9f1a3b5d7'
down_revision: str | None = 'b4d6f8a0c2e4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, no backfill needed — unlike last_login_at, NULL is the semantically correct
    # value for every existing row ("not yet notified about"), not a stand-in for missing data.
    # See app/core/notifications.py's DraftReadyNotificationSweep.
    op.add_column('content_items', sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('content_items', 'notified_at')
