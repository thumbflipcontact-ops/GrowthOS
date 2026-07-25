"""Async database engine and session factory.

One engine per process, created at startup (see app/main.py's lifespan) and disposed at
shutdown. Sessions are request-scoped, provided via the get_db dependency in app/api/deps.py
— never a module-level global session.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    # pydantic's PostgresDsn renders the driverless "postgresql://" scheme; asyncpg needs
    # the explicit "postgresql+asyncpg://" driver prefix.
    url = str(database_url)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return create_async_engine(url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A transaction-scoped session — commits on clean exit, rolls back on exception.
    Used outside the request lifecycle (jobs, scripts); request-scoped sessions go through
    app/api/deps.py's get_db instead."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
