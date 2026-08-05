"""Plugin connection endpoints — see docs/api/API_DESIGN.md and
docs/plugins/PLUGIN_ARCHITECTURE.md. This is what the frontend's generic
DynamicConnectionForm (driven by GET /plugins/catalog's config_schema) actually submits to;
no plugin-specific code exists here or ever should — see app/services/plugin_connection.py.

The oauth/start and oauth/disconnect routes below are project-scoped, like everything else
in this router — the OAuth callback itself is NOT (a provider's registered redirect_uri must
be one fixed URL), so it lives in its own router: see app/api/v1/oauth.py and
docs/auth/OAUTH2_ARCHITECTURE.md §3.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    get_plugin_catalog,
    get_settings_dep,
    require_active_subscription,
    require_project_access,
)
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.core.plugin_catalog import PluginCatalog
from app.models.identity import User
from app.models.plugin import PluginConnection
from app.models.project import Project
from app.schemas.plugin import (
    CreatePluginConnectionRequest,
    OAuthStartRequest,
    OAuthStartResponse,
    PluginConnectionResponse,
)
from app.services.oauth_connection import OAuthConnectionService
from app.services.plugin_connection import PluginConnectionService

router = APIRouter(prefix="/projects/{project_id}/plugin-connections", tags=["plugin-connections"])


@router.get("", response_model=list[PluginConnectionResponse])
async def list_plugin_connections(
    project: Project = Depends(require_project_access),
    session: AsyncSession = Depends(get_db),
    catalog: PluginCatalog = Depends(get_plugin_catalog),
) -> list[PluginConnection]:
    return await PluginConnectionService(session, catalog).list_for_project(project.id)


@router.post("", response_model=PluginConnectionResponse, status_code=201)
async def create_plugin_connection(
    body: CreatePluginConnectionRequest,
    # Connecting a new plugin account is where paid, metered API usage starts (a connection
    # is what search()/publish() get called against) — gated on an active subscription/trial,
    # not just project membership. See app/api/deps.py's require_active_subscription.
    project: Project = Depends(require_active_subscription),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    catalog: PluginCatalog = Depends(get_plugin_catalog),
) -> PluginConnection:
    return await PluginConnectionService(session, catalog).create(
        project_id=project.id,
        org_id=project.org_id,
        actor_user_id=current_user.id,
        plugin_key=body.plugin_key,
        config=body.config,
        capabilities_enabled=body.capabilities_enabled,
        label=body.label,
    )


@router.post("/{plugin_key}/oauth/start", response_model=OAuthStartResponse)
async def start_oauth_connection(
    plugin_key: str,
    body: OAuthStartRequest = OAuthStartRequest(),
    project: Project = Depends(require_project_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    catalog: PluginCatalog = Depends(get_plugin_catalog),
    settings: Settings = Depends(get_settings_dep),
) -> OAuthStartResponse:
    """Returns the provider's `authorize_url` for the frontend to navigate the browser to —
    see docs/auth/OAUTH2_ARCHITECTURE.md §3. Also how a reconnect is initiated: calling this
    again for a `label` with an existing `expired`/`error` connection is handled identically;
    the callback resolves whether it's a first connect or a reconnect."""
    service = OAuthConnectionService(session, catalog, settings)
    authorize_url = service.start(
        project_id=project.id, plugin_key=plugin_key, label=body.label, user_id=current_user.id
    )
    return OAuthStartResponse(authorize_url=authorize_url)


@router.post("/{connection_id}/oauth/disconnect", status_code=204, response_model=None)
async def disconnect_oauth_connection(
    connection_id: uuid.UUID,
    project: Project = Depends(require_project_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    catalog: PluginCatalog = Depends(get_plugin_catalog),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    connection = await session.get(PluginConnection, connection_id)
    if connection is None or connection.project_id != project.id:
        raise NotFoundError(
            "Plugin connection not found.", details={"connection_id": str(connection_id)}
        )

    service = OAuthConnectionService(session, catalog, settings)
    await service.disconnect(
        connection=connection, org_id=project.org_id, actor_user_id=current_user.id
    )
