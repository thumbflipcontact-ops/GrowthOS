from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.api_key import ApiKey
from app.repositories.base import Repository


class ApiKeyRepository(Repository[ApiKey]):
    model = ApiKey

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """The lookup require_api_key_project runs on every public-API request — matches
        api_keys' unique(key_hash) constraint exactly."""
        result = await self.session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: uuid.UUID) -> list[ApiKey]:
        result = await self.session.execute(
            select(ApiKey)
            .where(ApiKey.project_id == project_id)
            .order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_scoped(self, project_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.project_id == project_id)
        )
        return result.scalar_one_or_none()
