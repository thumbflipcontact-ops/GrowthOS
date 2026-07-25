"""add expired plugin_connection_status value

Revision ID: 0af53eb88b1e
Revises: 3353d5f04b9b
Create Date: 2026-07-25 15:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0af53eb88b1e'
down_revision: str | None = '3353d5f04b9b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A new value on an existing enum — additive, does not invalidate existing rows. Kept as
    # its own migration (not combined with the plugin_connections column changes in the next
    # revision) so this ALTER TYPE never shares a transaction with anything that could try to
    # use the new value — Postgres disallows using a freshly added enum value in the same
    # transaction that added it. See docs/auth/OAUTH2_ARCHITECTURE.md §7.
    op.execute("ALTER TYPE plugin_connection_status ADD VALUE IF NOT EXISTS 'expired'")


def downgrade() -> None:
    # Postgres has no `ALTER TYPE ... DROP VALUE` — removing an enum value requires
    # rebuilding the type (rename old, create new, migrate column, drop old), which is only
    # safe if nothing references it. Not implemented: rolling back past this revision while
    # any plugin_connections row has status='expired' is not a supported downgrade path.
    pass
