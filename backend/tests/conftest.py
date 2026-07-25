"""Shared pytest fixtures. See docs/testing/TESTING.md.

Integration tests run against a REAL Postgres — never SQLite — per docs/testing/TESTING.md's
"why Postgres-specific features need the real thing" reasoning. Since Docker isn't used for
local development/testing in this environment (see docker/README.md for the Docker-based
alternative, unchanged and still the documented option), `pgserver` provides a real, embedded
Postgres binary with no server install or Docker daemon required — session-scoped and torn
down completely at the end of the test run.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

# Every env var app/core/config.Settings requires, set before any app module is imported —
# several modules (e.g. app/jobs/*.py) read settings at import time.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use")
os.environ.setdefault("CREDENTIAL_MASTER_KEY", "test-master-key-not-for-production-use")
os.environ.setdefault("ENVIRONMENT", "local")


@pytest.fixture(scope="session")
def postgres_url() -> AsyncIterator[str] | str:
    import pgserver

    with tempfile.TemporaryDirectory(prefix="growthos-test-pg-") as tmpdir:
        server = pgserver.get_server(tmpdir, cleanup_mode="delete")
        server.psql("CREATE EXTENSION IF NOT EXISTS vector")
        uri = server.get_uri().replace("postgresql://", "postgresql+asyncpg://", 1)
        os.environ["DATABASE_URL"] = uri
        try:
            yield uri
        finally:
            server.cleanup()


@pytest.fixture(scope="session")
def _migrated_db(postgres_url: str) -> str:
    """Applies every Alembic migration once per test session — this is what makes the test
    suite an actual verification that `alembic upgrade head` works, not just that the
    SQLAlchemy models are internally consistent."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    command.upgrade(cfg, "head")
    return postgres_url


@pytest_asyncio.fixture
async def engine(_migrated_db: str):
    from app.core.db import create_engine

    eng = create_engine(_migrated_db)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    """One test = one outer transaction, rolled back at teardown — full isolation between
    tests without truncating tables between every test. Uses SQLAlchemy 2.0's
    `join_transaction_mode="create_savepoint"` so that even a test which calls
    `session.commit()` (as our request-scoped app/api/deps.get_db does) only commits to a
    SAVEPOINT nested inside the outer, never-committed transaction."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async with engine.connect() as conn:
        trans = await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with session_factory() as session:
            yield session
        await trans.rollback()


@pytest.fixture
def session_factory_for(db_session):
    """Some code under test (repositories, services) takes a `session_factory` rather than
    a session directly (e.g. app/core/scheduler.py). This adapts the single transactional
    `db_session` into that shape, so those tests still run inside the same rolled-back
    transaction as everything else."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def factory():
        yield db_session

    return factory


@pytest.fixture
def fake_redis():
    import fakeredis

    return fakeredis.FakeAsyncRedis()
