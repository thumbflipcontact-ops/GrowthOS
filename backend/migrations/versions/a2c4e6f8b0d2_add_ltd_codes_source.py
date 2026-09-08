"""add ltd_codes.source

Revision ID: a2c4e6f8b0d2
Revises: e9a1c3f5b7d9
Create Date: 2026-09-08 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a2c4e6f8b0d2'
down_revision: str | None = 'e9a1c3f5b7d9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'ltd_codes',
        sa.Column('source', sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('ltd_codes', 'source')
