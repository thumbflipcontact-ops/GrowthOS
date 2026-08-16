"""Public-API key management — dashboard-side, cookie-authed. See
app/api/deps.py's require_api_key_project for how a *minted* key later authenticates its own
requests against /public/v1/* — that's a completely separate auth path from this router.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_project_access
from app.models.identity import User
from app.models.project import Project
from app.schemas.api_key import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyResponse
from app.services.api_key import ApiKeyService

router = APIRouter(prefix="/projects/{project_id}/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreateResponse, status_code=201)
async def create_api_key(
    body: ApiKeyCreateRequest,
    project: Project = Depends(require_project_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    record, full_token = await ApiKeyService(session).create(
        project_id=project.id, org_id=project.org_id, actor_user_id=current_user.id, name=body.name
    )
    return ApiKeyCreateResponse(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        full_key=full_token,
        created_at=record.created_at,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    project: Project = Depends(require_project_access),
    session: AsyncSession = Depends(get_db),
) -> list[ApiKeyResponse]:
    keys = await ApiKeyService(session).list_for_project(project.id)
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.post("/{key_id}/revoke", response_model=ApiKeyResponse)
async def revoke_api_key(
    key_id: uuid.UUID,
    project: Project = Depends(require_project_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiKeyResponse:
    record = await ApiKeyService(session).revoke(
        project_id=project.id, org_id=project.org_id, actor_user_id=current_user.id, key_id=key_id
    )
    return ApiKeyResponse.model_validate(record)
