"""Public-API routes n8n's node calls directly — conversations (knowledge items), drafts
(content items awaiting/under review), replies (published content items), and the
approve/reject actions. Every route here is a thin wrapper: the actual logic already lives in
ContentApprovalService/ContentItemRepository/KnowledgeItemRepository — see
app/api/v1/content_items.py and app/api/v1/knowledge_items.py, the cookie-authed dashboard
routes wrapping the exact same underlying calls. The ClawHub skill for OpenClaw agents calls
this same set of routes.

Approve/reject via an API key is attributed to api_key.created_by_user_id, not left
actor-less — content_items' review_fields_consistent CHECK constraint requires a real
reviewed_by_user_id, and the human who generated the key is who's accountable for what it
does. See app/models/api_key.py's docstring.
"""

from __future__ import annotations

import uuid

from arq import ArqRedis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_arq_redis, get_db, require_api_key_project
from app.core.errors import AuthenticationError, NotFoundError
from app.models.api_key import ApiKey
from app.models.content import ContentItem
from app.models.project import Project
from app.repositories.content_repository import ContentItemRepository
from app.repositories.knowledge_repository import KnowledgeItemRepository
from app.schemas.content import ContentItemResponse
from app.schemas.knowledge import KnowledgeItemResponse
from app.schemas.public_content import PublicRejectDraftRequest
from app.services.content_approval import (
    MANUAL_PUBLISH_ONLY_PLATFORMS,
    ContentApprovalService,
    publish_job_id,
)

router = APIRouter(tags=["public-content"])


def _require_actor(api_key: ApiKey) -> uuid.UUID:
    """content_items' review_fields_consistent CHECK constraint requires a real
    reviewed_by_user_id — a key whose creator's account was deleted has nobody to attribute
    an approval/rejection to, so it's rejected here rather than left to violate the
    constraint (or silently attributed to nobody)."""
    if api_key.created_by_user_id is None:
        raise AuthenticationError(
            "This API key's creator no longer has an active account; revoke and reissue it."
        )
    return api_key.created_by_user_id


@router.get("/conversations", response_model=list[KnowledgeItemResponse])
async def list_conversations(
    project_and_key: tuple[Project, ApiKey] = Depends(require_api_key_project),
    session: AsyncSession = Depends(get_db),
    tag: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[KnowledgeItemResponse]:
    project, _api_key = project_and_key
    items = await KnowledgeItemRepository(session).list_by_project(
        project.id, tag=tag, limit=limit, offset=offset
    )
    return [KnowledgeItemResponse.model_validate(i) for i in items]


@router.get("/drafts", response_model=list[ContentItemResponse])
async def list_drafts(
    project_and_key: tuple[Project, ApiKey] = Depends(require_api_key_project),
    session: AsyncSession = Depends(get_db),
    status: str | None = Query(
        default="pending_review", description="Filter to this content_item_status."
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ContentItemResponse]:
    project, _api_key = project_and_key
    items = await ContentItemRepository(session).list_by_project(
        project.id, status=status, limit=limit, offset=offset
    )
    return [ContentItemResponse.model_validate(i) for i in items]


@router.get("/replies", response_model=list[ContentItemResponse])
async def list_replies(
    project_and_key: tuple[Project, ApiKey] = Depends(require_api_key_project),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ContentItemResponse]:
    project, _api_key = project_and_key
    items = await ContentItemRepository(session).list_by_project(
        project.id, status="published", limit=limit, offset=offset
    )
    return [ContentItemResponse.model_validate(i) for i in items]


@router.post("/drafts/{item_id}/approve", response_model=ContentItemResponse)
async def approve_draft(
    item_id: uuid.UUID,
    project_and_key: tuple[Project, ApiKey] = Depends(require_api_key_project),
    session: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_redis),
) -> ContentItem:
    project, api_key = project_and_key
    actor_user_id = _require_actor(api_key)

    current = await ContentItemRepository(session).get_scoped(project.id, item_id)
    if current is None:
        raise NotFoundError("Content item not found.", details={"item_id": str(item_id)})

    item = await ContentApprovalService(session).approve(
        project_id=project.id,
        item_id=item_id,
        expected_version=current.version,
        actor_user_id=actor_user_id,
        org_id=project.org_id,
    )
    if item.target_platform not in MANUAL_PUBLISH_ONLY_PLATFORMS:
        await arq_redis.enqueue_job(
            "publish_content_item",
            str(item.id),
            _job_id=publish_job_id(item.id),
            _queue_name="publish",
        )
    return item


@router.post("/drafts/{item_id}/reject", response_model=ContentItemResponse)
async def reject_draft(
    item_id: uuid.UUID,
    body: PublicRejectDraftRequest,
    project_and_key: tuple[Project, ApiKey] = Depends(require_api_key_project),
    session: AsyncSession = Depends(get_db),
) -> ContentItem:
    project, api_key = project_and_key
    actor_user_id = _require_actor(api_key)

    current = await ContentItemRepository(session).get_scoped(project.id, item_id)
    if current is None:
        raise NotFoundError("Content item not found.", details={"item_id": str(item_id)})

    return await ContentApprovalService(session).reject(
        project_id=project.id,
        item_id=item_id,
        expected_version=current.version,
        actor_user_id=actor_user_id,
        org_id=project.org_id,
        reason=body.reason,
    )
