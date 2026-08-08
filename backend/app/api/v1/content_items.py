"""Content item endpoints — see docs/api/API_DESIGN.md,
docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md, and
docs/reviews/PUBLISHING_WORKFLOW_IMPLEMENTATION_REPORT.md.

List/get are read-only. approve/reject/archive/mark-published are the *only* endpoints in
the entire API that can move a `content_item` out of `pending_review` (or, for archive, out
of `draft`; or, for mark-published, out of `approved`) — see ARCHITECTURE.md §8 and
`app/services/content_approval.py`, which does the actual state-machine enforcement; this
router only translates HTTP in and out of it. `approve` additionally enqueues the publish
job for every platform except X/Twitter (see the route below for why) — the only place a
publish attempt is triggered other than a manual `retry-publish` call. `mark-published` is
the one other place `status` becomes `published` — see its own docstring for why that's not
a violation of the publish worker owning that transition for every other platform.
"""

from __future__ import annotations

import uuid

from arq import ArqRedis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_arq_redis, get_current_user, get_db, require_project_access
from app.core.errors import InvalidStateTransition, NotFoundError
from app.models.audit import AuditLog
from app.models.content import ContentItem, ContentItemStatus, ContentPublishAttempt
from app.models.identity import User
from app.models.project import Project
from app.repositories.content_repository import (
    ContentItemRepository,
    ContentPublishAttemptRepository,
)
from app.repositories.knowledge_repository import KnowledgeItemRepository
from app.schemas.content import (
    ApproveContentItemRequest,
    ArchiveContentItemRequest,
    ContentItemResponse,
    MarkPublishedManuallyRequest,
    PublishAttemptResponse,
    RejectContentItemRequest,
)
from app.services.content_approval import ContentApprovalService

router = APIRouter(prefix="/projects/{project_id}/content-items", tags=["content-items"])

# X's own platform policy (Feb 2026) blocks a programmatic reply/quote unless the target
# post's author already @mentioned this account or quoted it first — every organically
# discovered post Conversation Finder finds fails that by construction, so an automated
# publish attempt for a twitter item would always 403, permanently, regardless of retries.
# Reproduced live: every attempt failed with "X returned 403: You can only reply to or quote
# posts where you are mentioned or are the author." Approving a twitter item skips the
# publish job entirely — the frontend instead shows the reply text and a link to the
# original post for a human to post manually, then confirms it via mark-published below.
_MANUAL_PUBLISH_ONLY_PLATFORMS = {"twitter"}


def _publish_job_id(item_id: uuid.UUID) -> str:
    """Deterministic Arq job id — a duplicate enqueue for the same content_item (a retried
    API request, or approve followed by a manual retry-publish before the first attempt has
    finished) is a no-op while one is already queued/running, per
    docs/jobs/BACKGROUND_JOBS.md's idempotency-keyed publish jobs."""
    return f"publish-{item_id}"


async def _with_source_post(
    session: AsyncSession, items: list[ContentItem]
) -> list[ContentItemResponse]:
    """content_items has no FK-joined data by default (see app/schemas/content.py's
    source_title/source_body docstring) — this batch-resolves each item's triggering
    knowledge_item in one query rather than one per row, then attaches its title/body_excerpt
    (the original post in full, not just the drafting agent's short evidence quotes) onto the
    response."""
    knowledge_item_ids = {item.knowledge_item_id for item in items if item.knowledge_item_id}
    knowledge_items = await KnowledgeItemRepository(session).list_by_ids(knowledge_item_ids)
    by_id = {ki.id: ki for ki in knowledge_items}
    responses = []
    for item in items:
        source = by_id.get(item.knowledge_item_id) if item.knowledge_item_id else None
        responses.append(
            ContentItemResponse.model_validate(item).model_copy(
                update={
                    "source_title": source.title if source else None,
                    "source_body": source.body_excerpt if source else None,
                }
            )
        )
    return responses


@router.get("", response_model=list[ContentItemResponse])
async def list_content_items(
    project: Project = Depends(require_project_access),
    session: AsyncSession = Depends(get_db),
    status: str | None = Query(default=None, description="Filter to this content_item_status."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ContentItemResponse]:
    items = await ContentItemRepository(session).list_by_project(
        project.id, status=status, limit=limit, offset=offset
    )
    return await _with_source_post(session, items)


@router.get("/{item_id}", response_model=ContentItemResponse)
async def get_content_item(
    item_id: uuid.UUID,
    project: Project = Depends(require_project_access),
    session: AsyncSession = Depends(get_db),
) -> ContentItemResponse:
    item = await ContentItemRepository(session).get_scoped(project.id, item_id)
    if item is None:
        raise NotFoundError("Content item not found.", details={"item_id": str(item_id)})
    return (await _with_source_post(session, [item]))[0]


@router.post("/{item_id}/approve", response_model=ContentItemResponse)
async def approve_content_item(
    item_id: uuid.UUID,
    body: ApproveContentItemRequest,
    project: Project = Depends(require_project_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_redis),
) -> ContentItem:
    item = await ContentApprovalService(session).approve(
        project_id=project.id,
        item_id=item_id,
        expected_version=body.version,
        actor_user_id=current_user.id,
        org_id=project.org_id,
    )
    if item.target_platform not in _MANUAL_PUBLISH_ONLY_PLATFORMS:
        await arq_redis.enqueue_job(
            "publish_content_item",
            str(item.id),
            _job_id=_publish_job_id(item.id),
            _queue_name="publish",
        )
    return item


@router.post("/{item_id}/mark-published", response_model=ContentItemResponse)
async def mark_content_item_published_manually(
    item_id: uuid.UUID,
    body: MarkPublishedManuallyRequest,
    project: Project = Depends(require_project_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ContentItem:
    """For a `_MANUAL_PUBLISH_ONLY_PLATFORMS` item a human posted themselves (approving it
    never enqueues a publish job for these — see the approve route above) — confirms that
    back to the system so it leaves the "ready to post" list. Only reachable from `approved`;
    see app/services/content_approval.py's mark_published_manually."""
    return await ContentApprovalService(session).mark_published_manually(
        project_id=project.id,
        item_id=item_id,
        expected_version=body.version,
        actor_user_id=current_user.id,
        org_id=project.org_id,
    )


@router.post("/{item_id}/reject", response_model=ContentItemResponse)
async def reject_content_item(
    item_id: uuid.UUID,
    body: RejectContentItemRequest,
    project: Project = Depends(require_project_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ContentItem:
    return await ContentApprovalService(session).reject(
        project_id=project.id,
        item_id=item_id,
        expected_version=body.version,
        actor_user_id=current_user.id,
        org_id=project.org_id,
        reason=body.reason,
    )


@router.post("/{item_id}/archive", response_model=ContentItemResponse)
async def archive_content_item(
    item_id: uuid.UUID,
    body: ArchiveContentItemRequest,
    project: Project = Depends(require_project_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ContentItem:
    return await ContentApprovalService(session).archive(
        project_id=project.id,
        item_id=item_id,
        expected_version=body.version,
        actor_user_id=current_user.id,
        org_id=project.org_id,
        reason=body.reason,
    )


@router.post("/{item_id}/retry-publish", response_model=ContentItemResponse, status_code=202)
async def retry_publish_content_item(
    item_id: uuid.UUID,
    project: Project = Depends(require_project_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_redis),
) -> ContentItem:
    """Manually re-triggers the publish job for an item stuck in `approved` with
    `publish_error` set (every retry Arq itself would have attempted is already exhausted) —
    see docs/jobs/BACKGROUND_JOBS.md: "surfaces in the dashboard for manual retry." Does not
    touch `content_items.status`/`version` itself; only the publish worker does that."""
    item = await ContentItemRepository(session).get_scoped(project.id, item_id)
    if item is None:
        raise NotFoundError("Content item not found.", details={"item_id": str(item_id)})
    if item.status != ContentItemStatus.APPROVED:
        raise InvalidStateTransition(
            f"content_item {item_id} cannot be retried: current status is "
            f"{item.status.value!r}, expected 'approved'.",
            details={"item_id": str(item_id), "current_status": item.status.value},
        )

    await arq_redis.enqueue_job(
        "publish_content_item",
        str(item.id),
        _job_id=_publish_job_id(item.id),
        _queue_name="publish",
    )
    session.add(
        AuditLog(
            org_id=project.org_id,
            actor_user_id=current_user.id,
            action="content_item.publish_retried",
            target=str(item.id),
        )
    )
    return item


@router.get("/{item_id}/publish-attempts", response_model=list[PublishAttemptResponse])
async def list_publish_attempts(
    item_id: uuid.UUID,
    project: Project = Depends(require_project_access),
    session: AsyncSession = Depends(get_db),
) -> list[ContentPublishAttempt]:
    item = await ContentItemRepository(session).get_scoped(project.id, item_id)
    if item is None:
        raise NotFoundError("Content item not found.", details={"item_id": str(item_id)})
    return await ContentPublishAttemptRepository(session).list_by_content_item(item.id)
