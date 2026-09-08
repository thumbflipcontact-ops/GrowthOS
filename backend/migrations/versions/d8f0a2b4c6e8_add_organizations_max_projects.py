"""add organizations.max_projects

Revision ID: d8f0a2b4c6e8
Revises: c7e9f1a3b5d7
Create Date: 2026-09-08 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd8f0a2b4c6e8'
down_revision: str | None = 'c7e9f1a3b5d7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, no backfill — NULL means "unlimited" (every existing org's actual behavior
    # today), not a stand-in for missing data. See app/api/v1/projects.py's create_project.
    op.add_column('organizations', sa.Column('max_projects', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('organizations', 'max_projects')
