from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ContentItemResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    type: str
    status: str
    body: str
    target_platform: str | None
    target_ref: str | None
    knowledge_item_id: uuid.UUID | None
    created_by_agent_run_id: uuid.UUID | None
    reviewed_by_user_id: uuid.UUID | None
    reviewed_at: datetime | None
    published_at: datetime | None
    publish_error: str | None
    confidence: Decimal
    reasoning: str | None
    evidence: list[str]
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
