"""add ltd_codes and organizations.is_ltd

Revision ID: e9a1c3f5b7d9
Revises: d8f0a2b4c6e8
Create Date: 2026-09-08 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e9a1c3f5b7d9'
down_revision: str | None = 'd8f0a2b4c6e8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'organizations',
        sa.Column('is_ltd', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    op.create_table(
        'ltd_codes',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('unredeemed', 'redeemed', name='ltd_code_status'),
            server_default=sa.text("'unredeemed'"),
            nullable=False,
        ),
        sa.Column('redeemed_by_org_id', sa.UUID(), nullable=True),
        sa.Column('redeemed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['redeemed_by_org_id'], ['organizations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )


def downgrade() -> None:
    op.drop_table('ltd_codes')
    op.execute('DROP TYPE IF EXISTS ltd_code_status')
    op.drop_column('organizations', 'is_ltd')
