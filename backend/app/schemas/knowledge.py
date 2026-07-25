from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class KnowledgeItemResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    platform: str
    url: str
    discovered_at: datetime
    problem: str | None
    industry: str | None
    product: str | None
    pain_point: str | None
    buying_intent: str
    suggested_reply: str | None
    suggested_article: str | None
    suggested_product_idea: str | None
    tags: list[str]
    confidence: Decimal
    outcome: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
