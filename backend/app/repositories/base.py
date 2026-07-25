"""Generic repository base — see docs/architecture/LOCKED_DECISIONS.md and
backend/README.md's intended structure. One repository per aggregate wraps the raw
SQLAlchemy session so services (and, in Phase 1, API route handlers directly) never build
ad hoc queries against models scattered through the codebase.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    """CRUD primitives shared by every concrete repository. Concrete repositories add
    query methods specific to their aggregate (e.g. get_by_slug) — this base intentionally
    stays thin rather than trying to anticipate every query shape.

    `id_` is typed `Any` deliberately: most tables use a UUID primary key, but
    plugin_catalog's is `plugin_key` (text) — see docs/database/SCHEMA.md. A repository
    whose model has a non-UUID key can call this unchanged rather than needing an override.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: Any) -> ModelT | None:
        return await self.session.get(self.model, id_)

    async def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self.session.delete(instance)
        await self.session.flush()

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[ModelT]:
        result = await self.session.execute(select(self.model).limit(limit).offset(offset))
        return list(result.scalars().all())
