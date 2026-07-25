from __future__ import annotations

from sqlalchemy import select

from app.models.identity import Organization
from app.repositories.base import Repository


class OrganizationRepository(Repository[Organization]):
    model = Organization

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.session.execute(select(Organization).where(Organization.slug == slug))
        return result.scalar_one_or_none()
