"""Knowledge item read endpoints. See docs/api/API_DESIGN.md and
docs/knowledge-base/KNOWLEDGE_BASE.md. Read-only — nothing writes `knowledge_items` through
the API; every row is agent-written, via app/services/knowledge_base.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_project_access
from app.models.knowledge import KnowledgeItem
from app.models.project import Project
from app.repositories.knowledge_repository import KnowledgeItemRepository
from app.schemas.knowledge import KnowledgeItemResponse

router = APIRouter(prefix="/projects/{project_id}/knowledge-items", tags=["knowledge-items"])


@router.get("", response_model=list[KnowledgeItemResponse])
async def list_knowledge_items(
    project: Project = Depends(require_project_access),
    session: AsyncSession = Depends(get_db),
    tag: str | None = Query(default=None, description="Filter to items tagged with this term."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[KnowledgeItem]:
    return await KnowledgeItemRepository(session).list_by_project(
        project.id, tag=tag, limit=limit, offset=offset
    )
