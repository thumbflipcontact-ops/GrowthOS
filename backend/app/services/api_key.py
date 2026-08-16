"""Create/list/revoke a project's public-API keys. See app/api/v1/api_keys.py (the
cookie-authed dashboard management surface) and app/api/deps.py's require_api_key_project
(the only place a key is ever verified against a request).

Mirrors app/services/agent_config.py's shape: plain __init__(session), one atomic thing per
method, an AuditLog row for every consequential write. No physical DELETE — matches this
codebase's revoke-not-delete convention (content_approval.py's archive(), agent_config.py's
disable path).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_keys import generate_api_key
from app.core.errors import NotFoundError
from app.models.api_key import ApiKey
from app.models.audit import AuditLog
from app.repositories.api_key_repository import ApiKeyRepository


class ApiKeyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.keys = ApiKeyRepository(session)

    async def create(
        self, *, project_id: uuid.UUID, org_id: uuid.UUID, actor_user_id: uuid.UUID, name: str
    ) -> tuple[ApiKey, str]:
        """Returns (record, full_token) — full_token exists only in this return value and the
        caller's HTTP response; nothing else in the system ever holds or logs it."""
        full_token, key_hash, key_prefix = generate_api_key()
        record = ApiKey(
            project_id=project_id,
            created_by_user_id=actor_user_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
        )
        self.session.add(record)
        await self.session.flush()

        self.session.add(
            AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action="api_key.created",
                target=key_prefix,
            )
        )
        await self.session.flush()
        return record, full_token

    async def list_for_project(self, project_id: uuid.UUID) -> list[ApiKey]:
        return await self.keys.list_by_project(project_id)

    async def revoke(
        self,
        *,
        project_id: uuid.UUID,
        org_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        key_id: uuid.UUID,
    ) -> ApiKey:
        record = await self.keys.get_scoped(project_id, key_id)
        if record is None:
            raise NotFoundError("API key not found.", details={"key_id": str(key_id)})
        record.revoked_at = datetime.now(UTC)
        await self.session.flush()

        self.session.add(
            AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action="api_key.revoked",
                target=record.key_prefix,
            )
        )
        await self.session.flush()
        return record
