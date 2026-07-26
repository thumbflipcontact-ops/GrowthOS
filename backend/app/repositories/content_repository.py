from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.content import ContentItem, ContentPublishAttempt
from app.repositories.base import Repository


class ContentItemRepository(Repository[ContentItem]):
    model = ContentItem

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ContentItem]:
        stmt = (
            select(ContentItem)
            .where(ContentItem.project_id == project_id)
            .order_by(ContentItem.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            stmt = stmt.where(ContentItem.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_scoped(self, project_id: uuid.UUID, item_id: uuid.UUID) -> ContentItem | None:
        """Like `get()`, but only returns the row if it belongs to `project_id` — the
        tenant-isolation check for the retrieve-one API endpoint (a valid `item_id` from a
        different project must 404, not leak the row)."""
        result = await self.session.execute(
            select(ContentItem).where(
                ContentItem.id == item_id, ContentItem.project_id == project_id
            )
        )
        return result.scalar_one_or_none()


class ContentPublishAttemptRepository(Repository[ContentPublishAttempt]):
    model = ContentPublishAttempt

    async def list_by_content_item(
        self, content_item_id: uuid.UUID
    ) -> list[ContentPublishAttempt]:
        result = await self.session.execute(
            select(ContentPublishAttempt)
            .where(ContentPublishAttempt.content_item_id == content_item_id)
            .order_by(ContentPublishAttempt.attempt_number)
        )
        return list(result.scalars().all())

    async def next_attempt_number(self, content_item_id: uuid.UUID) -> int:
        return len(await self.list_by_content_item(content_item_id)) + 1
