"""add oauth columns to plugin_connections

Revision ID: fdbcdc3ab26a
Revises: 0af53eb88b1e
Create Date: 2026-07-25 15:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'fdbcdc3ab26a'
down_revision: str | None = '0af53eb88b1e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'plugin_connections',
        sa.Column('label', sa.Text(), server_default=sa.text("'default'"), nullable=False),
    )
    op.add_column(
        'plugin_connections',
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'plugin_connections',
        sa.Column(
            'granted_scopes', sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False
        ),
    )

    op.drop_constraint('plugin_connections_project_id_plugin_key_key', 'plugin_connections', type_='unique')
    op.create_unique_constraint(
        'plugin_connections_project_id_plugin_key_label_key',
        'plugin_connections',
        ['project_id', 'plugin_key', 'label'],
    )

    # Hot-path index for the token-refresh sweep (app/jobs/oauth_refresh.py) — same partial-
    # index pattern already used for domain_events' undispatched-rows query.
    op.create_index(
        'idx_plugin_connections_oauth_refresh',
        'plugin_connections',
        ['token_expires_at'],
        unique=False,
        postgresql_where=sa.text("token_expires_at is not null and status = 'connected'"),
    )


def downgrade() -> None:
    op.drop_index(
        'idx_plugin_connections_oauth_refresh',
        table_name='plugin_connections',
        postgresql_where=sa.text("token_expires_at is not null and status = 'connected'"),
    )
    op.drop_constraint(
        'plugin_connections_project_id_plugin_key_label_key', 'plugin_connections', type_='unique'
    )
    op.create_unique_constraint(
        'plugin_connections_project_id_plugin_key_key', 'plugin_connections', ['project_id', 'plugin_key']
    )
    op.drop_column('plugin_connections', 'granted_scopes')
    op.drop_column('plugin_connections', 'token_expires_at')
    op.drop_column('plugin_connections', 'label')
