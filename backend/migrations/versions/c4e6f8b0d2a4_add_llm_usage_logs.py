"""add llm_usage_logs

Revision ID: c4e6f8b0d2a4
Revises: a2c4e6f8b0d2
Create Date: 2026-09-08 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4e6f8b0d2a4'
down_revision: str | None = 'a2c4e6f8b0d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'llm_usage_logs',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('purpose', sa.Text(), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Numeric(12, 6), nullable=False),
        sa.Column('agent_run_id', sa.UUID(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    # The whole point of this table is "spend by org over time" — see app/models/llm_usage.py.
    op.create_index(
        'idx_llm_usage_logs_org_created', 'llm_usage_logs', ['org_id', 'created_at']
    )


def downgrade() -> None:
    op.drop_index('idx_llm_usage_logs_org_created', table_name='llm_usage_logs')
    op.drop_table('llm_usage_logs')
