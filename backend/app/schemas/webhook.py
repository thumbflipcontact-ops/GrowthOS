from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class WebhookSubscriptionCreateRequest(BaseModel):
    target_url: str
    event_types: list[str] = Field(min_length=1)


class WebhookSubscriptionCreateResponse(BaseModel):
    """The only response that ever includes `secret` — shown exactly once, at creation, same
    pattern as ApiKeyCreateResponse's `full_key`."""

    id: uuid.UUID
    target_url: str
    event_types: list[str]
    secret: str
    enabled: bool
    created_at: datetime


class WebhookSubscriptionResponse(BaseModel):
    id: uuid.UUID
    target_url: str
    event_types: list[str]
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}
