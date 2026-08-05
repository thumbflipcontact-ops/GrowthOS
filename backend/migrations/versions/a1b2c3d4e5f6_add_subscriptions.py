"""add subscriptions

Revision ID: a1b2c3d4e5f6
Revises: 9dccb14c2c88
Create Date: 2026-08-04 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '9dccb14c2c88'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('polar_customer_id', sa.Text(), nullable=False),
        sa.Column('polar_subscription_id', sa.Text(), nullable=False),
        sa.Column('polar_product_id', sa.Text(), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'incomplete', 'trialing', 'active', 'past_due', 'canceled',
                name='subscription_status',
            ),
            nullable=False,
        ),
        sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id'),
        sa.UniqueConstraint('polar_subscription_id'),
    )


def downgrade() -> None:
    op.drop_table('subscriptions')
    op.execute('DROP TYPE IF EXISTS subscription_status')
