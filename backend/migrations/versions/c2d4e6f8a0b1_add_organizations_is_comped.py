"""add organizations.is_comped

Revision ID: c2d4e6f8a0b1
Revises: a1b2c3d4e5f6
Create Date: 2026-08-11 05:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c2d4e6f8a0b1'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'organizations',
        sa.Column('is_comped', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('organizations', 'is_comped')
