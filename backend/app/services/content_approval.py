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
# Archive is a Phase 2C addition (not in ARCHITECTURE.md §8's original diagram) — originally
# reachable from either pre-decision state, not from anything already decided or published.
# APPROVED was added once _MANUALLY_PUBLISHABLE_STATUSES existed: an approved item that's
# either stuck waiting on a human to post it manually, or stuck with a publish_error a human
# has decided isn't worth retrying, needs a way out of "approved" that isn't posting it —
# discarding it is exactly what archive already means for a pre-decision item, just reached
# from one status later. PUBLISHED was added the same way, one status later still: the
# frontend's "Posted" tab (app/frontend/app/posted/page.tsx) needs a "delete" action for an
# item the user no longer wants tracked there — archiving (not a hard delete) keeps the
# AuditLog trail and the row itself intact, consistent with every other removal in this
# codebase never being a physical DELETE.
_ARCHIVABLE_STATUSES = (
    ContentItemStatus.DRAFT,
    ContentItemStatus.PENDING_REVIEW,
    ContentItemStatus.APPROVED,
    ContentItemStatus.PUBLISHED,
)
# X's own platform policy (Feb 2026) blocks a programmatic reply/quote unless the target
# post's author already @mentioned this account or quoted it first — every organically
# discovered post fails that by construction, so a twitter item never actually reaches
# app/jobs/publish.py at all (see app/api/v1/content_items.py's approve route). An approved
# twitter item is instead posted by a human directly on X, then told to this service via
# mark_published_manually — the only status this can start from.
_MANUALLY_PUBLISHABLE_STATUSES = (ContentItemStatus.APPROVED,)

# Public (non-underscore): both app/api/v1/content_items.py's approve route and
# app/api/public/v1/content.py's public-API approve route need to decide whether to enqueue a
# publish job, and need the same idempotency-keyed job id if they do — one source of truth
# rather than two copies that could drift.
MANUAL_PUBLISH_ONLY_PLATFORMS = {"twitter"}


def publish_job_id(item_id: uuid.UUID) -> str:
    """Deterministic Arq job id — a duplicate enqueue for the same content_item (a retried
    API request, or approve followed by a manual retry-publish before the first attempt has
    finished) is a no-op while one is already queued/running, per
    docs/jobs/BACKGROUND_JOBS.md's idempotency-keyed publish jobs."""
    return f"publish-{item_id}"


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

    async def mark_published_manually(
        self,
        *,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        expected_version: int,
        actor_user_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> ContentItem:
        """A human posted this themselves (see the module-level comment on
        `_MANUALLY_PUBLISHABLE_STATUSES` for why) and is telling the system it's done.
        `_transition`'s generic UPDATE doesn't set `published_at` — every other
        `approved -> published` path (app/jobs/publish.py) sets it as part of recording a
        real API response, which doesn't exist here, so it's set directly after."""
        item = await self._transition(
            project_id=project_id,
            item_id=item_id,
            expected_version=expected_version,
            from_statuses=_MANUALLY_PUBLISHABLE_STATUSES,
            to_status=ContentItemStatus.PUBLISHED,
            actor_user_id=actor_user_id,
            org_id=org_id,
            action="content_item.published_manually",
            reason=None,
        )
        item.published_at = datetime.now(UTC)
        await self.session.flush()
        # This second flush (on top of _transition's own) triggers another onupdate=func.now()
        # write to updated_at — same class of bug as backend/app/services/agent_config.py's
        # fix earlier: without refreshing again here, updated_at is left expired, and FastAPI's
        # response serialization (running outside this method, after the request's async
        # context has moved on) can't lazily load it — MissingGreenlet.
        await self.session.refresh(item)
        return item

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
