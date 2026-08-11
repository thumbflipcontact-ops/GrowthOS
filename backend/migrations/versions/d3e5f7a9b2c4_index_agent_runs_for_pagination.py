"""index agent_runs for pagination

Revision ID: d3e5f7a9b2c4
Revises: c2d4e6f8a0b1
Create Date: 2026-08-11 08:10:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd3e5f7a9b2c4'
down_revision: str | None = 'c2d4e6f8a0b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        'idx_agent_runs_project_key_created',
        'agent_runs',
        ['project_id', 'agent_key', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('idx_agent_runs_project_key_created', table_name='agent_runs')
