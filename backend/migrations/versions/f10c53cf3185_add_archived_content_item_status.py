"""add archived content_item_status value

Revision ID: f10c53cf3185
Revises: 158996aaa01b
Create Date: 2026-07-26 09:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f10c53cf3185'
down_revision: str | None = '158996aaa01b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A new value on an existing enum — additive, does not invalidate existing rows. Kept as
    # its own migration (not combined with the next revision's new table) for the same reason
    # 0af53eb88b1e (add expired plugin_connection_status value) was kept separate: Postgres
    # disallows using a freshly added enum value in the same transaction that added it.
    op.execute("ALTER TYPE content_item_status ADD VALUE IF NOT EXISTS 'archived'")


def downgrade() -> None:
    # Postgres has no `ALTER TYPE ... DROP VALUE` — see 0af53eb88b1e's identical note. Not
    # implemented: rolling back past this revision while any content_items row has
    # status='archived' is not a supported downgrade path.
    pass
