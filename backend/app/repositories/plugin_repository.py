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

    async def get_by_project_plugin_and_label(
        self, project_id: uuid.UUID, plugin_key: str, label: str = "default"
    ) -> PluginConnection | None:
        """`label` disambiguates multiple connections to the same plugin within one project
        (two Reddit accounts, two Slack workspaces) — see
        docs/auth/OAUTH2_ARCHITECTURE.md §2. Matches `plugin_connections`'s
        `unique(project_id, plugin_key, label)` constraint exactly."""
        result = await self.session.execute(
            select(PluginConnection).where(
                PluginConnection.project_id == project_id,
                PluginConnection.plugin_key == plugin_key,
                PluginConnection.label == label,
            )
        )
        return result.scalar_one_or_none()
