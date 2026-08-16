from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ApiKeyCreateRequest(BaseModel):
    name: str


class ApiKeyCreateResponse(BaseModel):
    """The only response that ever includes `full_key` — shown exactly once, at creation.
    Every other read of an api_keys row (list) uses ApiKeyResponse instead, which omits it."""

    id: uuid.UUID
    name: str
    key_prefix: str
    full_key: str
    created_at: datetime


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
