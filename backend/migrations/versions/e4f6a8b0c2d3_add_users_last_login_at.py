"""add users.last_login_at

Revision ID: e4f6a8b0c2d3
Revises: d3e5f7a9b2c4
Create Date: 2026-08-16 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e4f6a8b0c2d3'
down_revision: str | None = 'd3e5f7a9b2c4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
    # Backfill existing rows so nobody looks "never logged in" (and gets mass-disabled by
    # app/core/agent_lifecycle.py's inactivity sweep) the moment this ships — created_at is
    # the best available stand-in for "last known activity" for a row with no other signal.
    op.execute('UPDATE users SET last_login_at = created_at WHERE last_login_at IS NULL')


def downgrade() -> None:
    op.drop_column('users', 'last_login_at')
