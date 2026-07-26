"""add content_publish_attempts

Revision ID: 9dccb14c2c88
Revises: f10c53cf3185
Create Date: 2026-07-26 09:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9dccb14c2c88'
down_revision: str | None = 'f10c53cf3185'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'content_publish_attempts',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('content_item_id', sa.UUID(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('published_url', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['content_item_id'], ['content_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_content_publish_attempts_item',
        'content_publish_attempts',
        ['content_item_id', 'attempt_number'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('idx_content_publish_attempts_item', table_name='content_publish_attempts')
    op.drop_table('content_publish_attempts')
