from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update

from app.models.content import ContentItem, ContentItemStatus, ContentPublishAttempt
from app.models.knowledge import KnowledgeItem
from app.repositories.base import Repository


class ContentItemRepository(Repository[ContentItem]):
    model = ContentItem

    async def list_pending_review_unnotified(self) -> list[ContentItem]:
        """Every content_item that reached pending_review but hasn't been emailed about yet
        — see app/core/notifications.py's DraftReadyNotificationSweep. Global, not
        project-scoped: the sweep groups results by project_id itself."""
        result = await self.session.execute(
            select(ContentItem).where(
                ContentItem.status == ContentItemStatus.PENDING_REVIEW,
                ContentItem.notified_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def mark_notified(self, item_ids: list[uuid.UUID], *, now: datetime) -> None:
        if not item_ids:
            return
        await self.session.execute(
            update(ContentItem).where(ContentItem.id.in_(item_ids)).values(notified_at=now)
        )

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ContentItem]:
        stmt = select(ContentItem).where(ContentItem.project_id == project_id)
        if status is not None:
            stmt = stmt.where(ContentItem.status == status)

        if status == ContentItemStatus.PENDING_REVIEW.value:
            # The Approval Inbox specifically — surface the strongest leads first, not just
            # the most recently drafted ones. A draft's own `ContentItem.confidence` is the
            # model's confidence in *its reply*, a different axis from how good the lead
            # itself is; the lead-relevance score the LLM scoring pass produces
            # (agents/conversation_finder/prompts.py) lives on the source KnowledgeItem, so
            # this joins to it. NULLS LAST covers a knowledge_item that's since been deleted
            # (knowledge_item_id survives via ON DELETE SET NULL) or a draft with no source at
            # all — falls to the end rather than sorting as if it were the least relevant.
            # created_at DESC is only the tiebreak for equal/missing scores, not the primary
            # order, unlike every other status this method serves (ready-to-post, posted),
            # which stay chronological — order there reflects a real posting queue, not lead
            # quality.
            stmt = stmt.outerjoin(
                KnowledgeItem, ContentItem.knowledge_item_id == KnowledgeItem.id
            ).order_by(
                KnowledgeItem.confidence.desc().nulls_last(), ContentItem.created_at.desc()
            )
        else:
            stmt = stmt.order_by(ContentItem.created_at.desc())

        stmt = stmt.limit(limit).offset(offset)
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
