"""Integration tests for app/core/migration_check.py — see
docs/reviews/PRODUCTION_READINESS_REVIEW.md O7 and
docs/reviews/PRODUCTION_HARDENING_REPORT.md.
"""

from __future__ import annotations

import pytest

import app.core.migration_check as migration_check
from app.core.migration_check import DatabaseNotMigrated, verify_database_is_migrated

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_passes_silently_when_the_database_is_at_head(engine) -> None:
    # `engine` (see conftest.py) is built against `_migrated_db`, which runs every real
    # Alembic migration to head before any test uses it — this is genuinely the real,
    # correct state a healthy deployment would be in.
    await verify_database_is_migrated(engine)


@pytest.mark.asyncio
async def test_raises_when_the_code_expects_a_different_head(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Patches the *expected* revision rather than mutating the real (shared, session-scoped)
    # database's alembic_version row — this exercises the same comparison the real mismatch
    # case hits, without risking leaving the shared test database in a broken state for every
    # other test in the session.
    monkeypatch.setattr(
        migration_check, "_expected_head_revision", lambda: "a-revision-that-does-not-exist"
    )

    with pytest.raises(DatabaseNotMigrated, match="a-revision-that-does-not-exist"):
        await verify_database_is_migrated(engine)


@pytest.mark.asyncio
async def test_is_a_noop_when_there_are_no_migrations_to_compare_against(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(migration_check, "_expected_head_revision", lambda: None)
    await verify_database_is_migrated(engine)  # must not raise
