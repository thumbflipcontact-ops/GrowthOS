"""Content item (draft) read endpoints — see docs/api/API_DESIGN.md and
docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md. Read-only, matching Phase 2B's scope:
nothing writes `content_items` through the API; every row is agent-written (see
app/services/content_drafts.py). Listing/retrieving drafts for human review is as far as
Phase 2B goes — approve/reject endpoints are Phase 2C (`ContentApprovalService`).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_project_access
from app.core.errors import NotFoundError
from app.models.content import ContentItem
from app.models.project import Project
from app.repositories.content_repository import ContentItemRepository
from app.schemas.content import ContentItemResponse

router = APIRouter(prefix="/projects/{project_id}/content-items", tags=["content-items"])


@router.get("", response_model=list[ContentItemResponse])
async def list_content_items(
    project: Project = Depends(require_project_access),
    session: AsyncSession = Depends(get_db),
    status: str | None = Query(default=None, description="Filter to this content_item_status."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ContentItem]:
    return await ContentItemRepository(session).list_by_project(
        project.id, status=status, limit=limit, offset=offset
    )


@router.get("/{item_id}", response_model=ContentItemResponse)
async def get_content_item(
    item_id: uuid.UUID,
    project: Project = Depends(require_project_access),
    session: AsyncSession = Depends(get_db),
) -> ContentItem:
    item = await ContentItemRepository(session).get_scoped(project.id, item_id)
    if item is None:
        raise NotFoundError("Content item not found.", details={"item_id": str(item_id)})
    return item
