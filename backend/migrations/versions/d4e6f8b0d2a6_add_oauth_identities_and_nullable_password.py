"""add oauth_identities and make users.password_hash nullable

Revision ID: d4e6f8b0d2a6
Revises: c4e6f8b0d2a4
Create Date: 2026-09-11 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e6f8b0d2a6'
down_revision: str | None = 'c4e6f8b0d2a4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column('users', 'password_hash', existing_type=sa.Text(), nullable=True)
    op.create_table(
        'oauth_identities',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.Text(), nullable=False),
        sa.Column('provider_user_id', sa.Text(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_user_id'),
    )


def downgrade() -> None:
    op.drop_table('oauth_identities')
    op.alter_column('users', 'password_hash', existing_type=sa.Text(), nullable=False)
