"""Project endpoints — see docs/api/API_DESIGN.md. Basic CRUD only; ICP/brand-voice content
is opaque JSON at this layer (agents interpret it — out of Phase 1 scope, see ROADMAP.md)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_org_access, require_project_access
from app.core.errors import ValidationError
from app.models.identity import Organization
from app.models.project import Project
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import CreateProjectRequest, ProjectResponse

router = APIRouter(tags=["projects"])


@router.get("/orgs/{org_id}/projects", response_model=list[ProjectResponse])
async def list_projects(
    organization: Organization = Depends(require_org_access),
    session: AsyncSession = Depends(get_db),
) -> list[Project]:
    return await ProjectRepository(session).list_by_org(organization.id)


@router.post("/orgs/{org_id}/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: CreateProjectRequest,
    organization: Organization = Depends(require_org_access),
    session: AsyncSession = Depends(get_db),
) -> Project:
    repo = ProjectRepository(session)
    if await repo.get_by_slug(organization.id, body.slug) is not None:
        raise ValidationError("A project with this slug already exists in this organization.")

    project = Project(org_id=organization.id, name=body.name, slug=body.slug)
    return await repo.add(project)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project: Project = Depends(require_project_access)) -> Project:
    return project
