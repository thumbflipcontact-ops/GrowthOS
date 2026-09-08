"""Project endpoints — see docs/api/API_DESIGN.md. Basic CRUD only; ICP/brand-voice content
is opaque JSON at this layer (agents interpret it — out of Phase 1 scope, see ROADMAP.md)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_plugin_catalog, require_org_access, require_project_access
from app.core.errors import ValidationError
from app.core.plugin_catalog import PluginCatalog
from app.models.identity import Organization
from app.models.plugin import PluginCapability, PluginConnection, PluginConnectionStatus
from app.models.project import Project
from app.repositories.plugin_repository import PluginConnectionRepository
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
    catalog: PluginCatalog = Depends(get_plugin_catalog),
) -> Project:
    repo = ProjectRepository(session)
    if await repo.get_by_slug(organization.id, body.slug) is not None:
        raise ValidationError("A project with this slug already exists in this organization.")

    # organization.max_projects is NULL (unlimited) for every regular subscriber today — see
    # its own docstring in app/models/identity.py. Only orgs with an explicit ceiling set
    # (e.g. a lifetime-deal tier) are actually gated here.
    if organization.max_projects is not None:
        existing_count = len(await repo.list_by_org(organization.id))
        if existing_count >= organization.max_projects:
            raise ValidationError(
                f"This plan allows up to {organization.max_projects} project"
                f"{'s' if organization.max_projects != 1 else ''}. Delete one first, or "
                "upgrade to a higher tier.",
                details={
                    "max_projects": organization.max_projects,
                    "existing_count": existing_count,
                },
            )

    project = Project(org_id=organization.id, name=body.name, slug=body.slug)
    project = await repo.add(project)

    # Reddit discovery works with no connected account (plugins/reddit/plugin.py's search()
    # is unauthenticated, sitewide) — auto-connecting SEARCHABLE here, with no credentials at
    # all, is what gives every project working lead discovery from the moment it's created,
    # with zero OAuth flow needed. Safe by construction:
    # app/core/plugin_registry.py::_resolve_credentials() already returns None (not an error)
    # for any auth_type when credentials_encrypted is unset. Connecting a real Reddit account
    # later (to enable publish()) upserts this same row via the ordinary OAuth callback
    # (app/services/oauth_connection.py) rather than creating a second one.
    if catalog.get("reddit") is not None:
        await PluginConnectionRepository(session).add(
            PluginConnection(
                project_id=project.id,
                plugin_key="reddit",
                capabilities_enabled=[PluginCapability.SEARCHABLE],
                config={"subreddits": []},
                status=PluginConnectionStatus.CONNECTED,
            )
        )

    return project


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project: Project = Depends(require_project_access)) -> Project:
    return project
