"""add api_keys, webhook_subscriptions, webhook_deliveries

Revision ID: f5a7b9c1d3e5
Revises: e4f6a8b0c2d3
Create Date: 2026-08-16 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f5a7b9c1d3e5'
down_revision: str | None = 'e4f6a8b0c2d3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'api_keys',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('created_by_user_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('key_hash', sa.Text(), nullable=False),
        sa.Column('key_prefix', sa.Text(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash'),
    )
    op.create_index('idx_api_keys_project', 'api_keys', ['project_id'])

    op.create_table(
        'webhook_subscriptions',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('created_by_api_key_id', sa.UUID(), nullable=True),
        sa.Column('target_url', sa.Text(), nullable=False),
        sa.Column(
            'event_types', sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"), nullable=False,
        ),
        sa.Column('secret', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_api_key_id'], ['api_keys.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_webhook_subscriptions_project', 'webhook_subscriptions', ['project_id'])

    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('webhook_subscription_id', sa.UUID(), nullable=False),
        sa.Column('domain_event_id', sa.UUID(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('pending', 'success', 'failed', name='webhook_delivery_status'),
            server_default=sa.text("'pending'"), nullable=False,
        ),
        sa.Column('attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_response_status', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['webhook_subscription_id'], ['webhook_subscriptions.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(['domain_event_id'], ['domain_events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'webhook_subscription_id', 'domain_event_id', name='uq_webhook_delivery_once_per_event'
        ),
    )
    op.create_index(
        'idx_webhook_deliveries_pending',
        'webhook_deliveries',
        ['next_attempt_at'],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index('idx_webhook_deliveries_pending', table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')
    op.execute('DROP TYPE IF EXISTS webhook_delivery_status')

    op.drop_index('idx_webhook_subscriptions_project', table_name='webhook_subscriptions')
    op.drop_table('webhook_subscriptions')

    op.drop_index('idx_api_keys_project', table_name='api_keys')
    op.drop_table('api_keys')
