"""The global OAuth callback route — see docs/auth/OAUTH2_ARCHITECTURE.md §3.

Deliberately NOT project-scoped in its path, unlike every other plugin-connection route: the
redirect_uri registered with an OAuth provider must be one fixed URL, so project/plugin/label
identity travels inside the signed `state` parameter instead (verified inside
OAuthConnectionService.handle_callback) — see app/api/v1/plugin_connections.py for the
project-scoped oauth/start and oauth/disconnect routes that DO belong under that prefix.

This route is hit by a top-level browser redirect from the provider, not a frontend fetch()
call — so outcomes (success or failure) are communicated by redirecting the browser back to
`Settings.oauth_frontend_redirect_url` with a query param, never a raw JSON error body a user
would otherwise see rendered as text in their browser.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_plugin_catalog, get_settings_dep
from app.core.config import Settings
from app.core.errors import GrowthOSError
from app.core.plugin_catalog import PluginCatalog
from app.models.identity import User
from app.services.oauth_connection import OAuthConnectionService

router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/{plugin_key}/callback")
async def oauth_callback(
    plugin_key: str,
    code: str = Query(...),
    state: str = Query(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    catalog: PluginCatalog = Depends(get_plugin_catalog),
    settings: Settings = Depends(get_settings_dep),
) -> RedirectResponse:
    """`plugin_key` in the path identifies which provider redirected here (each
    OAuth-capable plugin has its own registered callback URL) but is not itself trusted for
    anything beyond that — the signed `state` parameter is the sole source of truth for which
    project/plugin/label/user this callback belongs to (docs/auth/OAUTH2_ARCHITECTURE.md §6).
    """
    service = OAuthConnectionService(session, catalog, settings)
    try:
        connection = await service.handle_callback(
            code=code, state_token=state, current_user_id=current_user.id
        )
    except GrowthOSError as exc:
        query = urlencode({"error": exc.code, "plugin_key": plugin_key})
        return RedirectResponse(f"{settings.oauth_frontend_redirect_url}?{query}", status_code=302)

    query = urlencode({"connected": connection.plugin_key, "label": connection.label})
    return RedirectResponse(f"{settings.oauth_frontend_redirect_url}?{query}", status_code=302)
