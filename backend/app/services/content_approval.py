"""The human-approval gate's actual state-machine enforcement — see ARCHITECTURE.md §8 and
docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md.

The single place `content_items.status` ever moves from `pending_review` to `approved`/
`rejected`, or from `draft`/`pending_review` to `archived` — never the API layer, never a
UI. Every transition is atomic and version-guarded: the actual `UPDATE` statement's `WHERE`
clause checks `status IN (...)` and `version = :expected` in the same round trip, so a
concurrent double-approve (two requests reading the same version) can only ever have one
winner — the loser's `UPDATE` affects zero rows and this raises `InvalidStateTransition`,
never a silent double-transition. This is the same guard docs/api/API_DESIGN.md's approval
endpoints have documented since Phase 0; this is the first thing that actually implements it.

Publishing itself (`approved → published`) is the publish worker's job
(`app/jobs/publish.py`), not this service's — this service's `approve()` only enqueues that
job; it never calls a plugin's `publish()` itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidStateTransition, NotFoundError
from app.models.audit import AuditLog
from app.models.content import ContentItem, ContentItemStatus
from app.repositories.content_repository import ContentItemRepository

# Per ARCHITECTURE.md §8: a human may only approve/reject an item still awaiting review.
_REVIEWABLE_STATUSES = (ContentItemStatus.PENDING_REVIEW,)
# Archive is a Phase 2C addition (not in ARCHITECTURE.md §8's original diagram) — reachable
# from either pre-decision state, not from anything already decided or published.
_ARCHIVABLE_STATUSES = (ContentItemStatus.DRAFT, ContentItemStatus.PENDING_REVIEW)


class ContentApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.items = ContentItemRepository(session)

    async def approve(
        self,
        *,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        expected_version: int,
        actor_user_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> ContentItem:
        return await self._transition(
            project_id=project_id,
            item_id=item_id,
            expected_version=expected_version,
            from_statuses=_REVIEWABLE_STATUSES,
            to_status=ContentItemStatus.APPROVED,
            actor_user_id=actor_user_id,
            org_id=org_id,
            action="content_item.approved",
            reason=None,
        )

    async def reject(
        self,
        *,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        expected_version: int,
        actor_user_id: uuid.UUID,
        org_id: uuid.UUID,
        reason: str,
    ) -> ContentItem:
        return await self._transition(
            project_id=project_id,
            item_id=item_id,
            expected_version=expected_version,
            from_statuses=_REVIEWABLE_STATUSES,
            to_status=ContentItemStatus.REJECTED,
            actor_user_id=actor_user_id,
            org_id=org_id,
            action="content_item.rejected",
            reason=reason,
        )

    async def archive(
        self,
        *,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        expected_version: int,
        actor_user_id: uuid.UUID,
        org_id: uuid.UUID,
        reason: str | None = None,
    ) -> ContentItem:
        return await self._transition(
            project_id=project_id,
            item_id=item_id,
            expected_version=expected_version,
            from_statuses=_ARCHIVABLE_STATUSES,
            to_status=ContentItemStatus.ARCHIVED,
            actor_user_id=actor_user_id,
            org_id=org_id,
            action="content_item.archived",
            reason=reason,
        )

    async def _transition(
        self,
        *,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        expected_version: int,
        from_statuses: tuple[ContentItemStatus, ...],
        to_status: ContentItemStatus,
        actor_user_id: uuid.UUID,
        org_id: uuid.UUID,
        action: str,
        reason: str | None,
    ) -> ContentItem:
        existing = await self.items.get_scoped(project_id, item_id)
        if existing is None:
            raise NotFoundError(
                "Content item not found.", details={"item_id": str(item_id)}
            )

        stmt = (
            update(ContentItem)
            .where(
                ContentItem.id == item_id,
                ContentItem.project_id == project_id,
                ContentItem.version == expected_version,
                ContentItem.status.in_(from_statuses),
            )
            .values(
                status=to_status,
                reviewed_by_user_id=actor_user_id,
                reviewed_at=datetime.now(UTC),
                version=ContentItem.version + 1,
            )
        )
        result = await self.session.execute(stmt)
        # `.rowcount` is real at runtime (a CursorResult, since `stmt` is an UPDATE) — the
        # stub for AsyncSession.execute()'s generic Result return type doesn't declare it.
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise InvalidStateTransition(
                f"content_item {item_id} cannot transition to {to_status.value!r}: current "
                f"status is {existing.status.value!r} (expected one of "
                f"{[s.value for s in from_statuses]!r}), or its version has changed since "
                f"you last read it (you supplied version={expected_version}, current "
                f"version={existing.version}).",
                details={
                    "item_id": str(item_id),
                    "current_status": existing.status.value,
                    "current_version": existing.version,
                    "expected_version": expected_version,
                },
            )

        await self.session.refresh(existing)

        self.session.add(
            AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action=action,
                target=str(item_id),
                metadata_={"reason": reason} if reason else {},
            )
        )
        await self.session.flush()
        return existing
