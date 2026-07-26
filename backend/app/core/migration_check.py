"""Fail-fast startup check that the connected database is at the migration revision this
code expects — see docs/reviews/PRODUCTION_READINESS_REVIEW.md O7 and
docs/reviews/PRODUCTION_HARDENING_REPORT.md.

Migrations are deliberately NOT auto-run at process startup — see
docs/deployment/DEPLOYMENT.md's "a migration failure should block the deploy loudly, not
degrade into the app half-starting." This check enforces that same principle a different way:
instead of a stale schema causing a confusing failure at the first query that touches a
missing column/table, every process that connects to the database refuses to start at all
when the schema is behind. `python scripts/migrate.py` remains the one place migrations
actually run.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseNotMigrated(RuntimeError):
    pass


def _expected_head_revision() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_dir = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


async def verify_database_is_migrated(engine: AsyncEngine) -> None:
    """Raises DatabaseNotMigrated if the connected database's alembic_version doesn't match
    this code's migration head. Called once at process startup (see app/main.py's lifespan
    and every Arq worker's startup()) — never on a per-request/per-job hot path."""
    expected = _expected_head_revision()
    if expected is None:
        return  # no migrations exist in this checkout — nothing to verify against

    async with engine.connect() as conn:
        try:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            actual = result.scalar_one_or_none()
        except Exception as exc:
            raise DatabaseNotMigrated(
                "Could not read the alembic_version table — has `python scripts/migrate.py` "
                f"ever been run against this database? ({exc.__class__.__name__}: {exc})"
            ) from exc

    if actual != expected:
        raise DatabaseNotMigrated(
            f"Database is at migration {actual!r}, but this code expects {expected!r}. Run "
            "`python scripts/migrate.py` before starting this process."
        )
