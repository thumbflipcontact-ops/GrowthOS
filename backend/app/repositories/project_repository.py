from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.project import Project
from app.repositories.base import Repository


class ProjectRepository(Repository[Project]):
    model = Project

    async def list_by_org(self, org_id: uuid.UUID) -> list[Project]:
        result = await self.session.execute(select(Project).where(Project.org_id == org_id))
        return list(result.scalars().all())

    async def get_by_slug(self, org_id: uuid.UUID, slug: str) -> Project | None:
        result = await self.session.execute(
            select(Project).where(Project.org_id == org_id, Project.slug == slug)
        )
        return result.scalar_one_or_none()
