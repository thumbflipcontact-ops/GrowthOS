from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.plugin import PluginCatalogEntry, PluginConnection
from app.repositories.base import Repository


class PluginCatalogRepository(Repository[PluginCatalogEntry]):
    model = PluginCatalogEntry

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[PluginCatalogEntry]:
        result = await self.session.execute(
            select(PluginCatalogEntry).order_by(PluginCatalogEntry.plugin_key).limit(limit).offset(offset)
        )
        return list(result.scalars().all())


class PluginConnectionRepository(Repository[PluginConnection]):
    model = PluginConnection

    async def list_by_project(self, project_id: uuid.UUID) -> list[PluginConnection]:
        result = await self.session.execute(
            select(PluginConnection).where(PluginConnection.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get_by_project_and_key(
        self, project_id: uuid.UUID, plugin_key: str
    ) -> PluginConnection | None:
        result = await self.session.execute(
            select(PluginConnection).where(
                PluginConnection.project_id == project_id, PluginConnection.plugin_key == plugin_key
            )
        )
        return result.scalar_one_or_none()
