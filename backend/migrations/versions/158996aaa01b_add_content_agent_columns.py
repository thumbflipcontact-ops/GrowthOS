"""add content agent columns

Revision ID: 158996aaa01b
Revises: fdbcdc3ab26a
Create Date: 2026-07-25 21:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '158996aaa01b'
down_revision: str | None = 'fdbcdc3ab26a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Grounding text captured verbatim at discovery time (Conversation Finder) — a real
    # consumer (Content Agent) needs this to draft and cite from; nothing needed it before.
    op.add_column('knowledge_items', sa.Column('title', sa.Text(), nullable=True))
    op.add_column('knowledge_items', sa.Column('body_excerpt', sa.Text(), nullable=True))
    op.add_column(
        'knowledge_items',
        sa.Column(
            'platform_metadata',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # The drafting agent's own self-assessment.
    op.add_column(
        'content_items',
        sa.Column(
            'confidence',
            sa.Numeric(3, 2),
            server_default=sa.text('0.0'),
            nullable=False,
        ),
    )
    op.add_column('content_items', sa.Column('reasoning', sa.Text(), nullable=True))
    op.add_column(
        'content_items',
        sa.Column(
            'evidence',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        'content_items_confidence_check', 'content_items', 'confidence between 0 and 1'
    )


def downgrade() -> None:
    op.drop_constraint('content_items_confidence_check', 'content_items', type_='check')
    op.drop_column('content_items', 'evidence')
    op.drop_column('content_items', 'reasoning')
    op.drop_column('content_items', 'confidence')

    op.drop_column('knowledge_items', 'platform_metadata')
    op.drop_column('knowledge_items', 'body_excerpt')
    op.drop_column('knowledge_items', 'title')
