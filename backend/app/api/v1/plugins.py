"""Plugin catalog endpoint — see docs/api/API_DESIGN.md and
docs/decisions/0009-plugin-config-schema-dynamic-ui.md. Drives the frontend's generic
DynamicConnectionForm; no plugin-specific code exists here or ever should."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.identity import User
from app.models.plugin import PluginCatalogEntry
from app.repositories.plugin_repository import PluginCatalogRepository
from app.schemas.plugin import PluginCatalogEntryResponse

router = APIRouter(prefix="/plugins", tags=["plugins"])


@router.get("/catalog", response_model=list[PluginCatalogEntryResponse])
async def get_plugin_catalog(
    _current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[PluginCatalogEntry]:
    return await PluginCatalogRepository(session).list_all()
