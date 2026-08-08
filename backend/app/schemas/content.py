from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ApproveContentItemRequest(BaseModel):
    """See app/services/content_approval.py. `version` is the value the client last read —
    the optimistic-concurrency guard rejects (409) if it doesn't match the row's current
    version, per docs/api/API_DESIGN.md."""

    version: int = Field(ge=1)


class MarkPublishedManuallyRequest(BaseModel):
    """See app/services/content_approval.py's mark_published_manually — for a platform
    (currently just X/Twitter) whose own policy blocks this system from posting on the
    project's behalf, so a human posted it directly and is confirming that here."""

    version: int = Field(ge=1)


class RejectContentItemRequest(BaseModel):
    version: int = Field(ge=1)
    reason: str = Field(min_length=1)


class ArchiveContentItemRequest(BaseModel):
    version: int = Field(ge=1)
    reason: str | None = None


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
    # The triggering knowledge_item's own title/body_excerpt — the original post in full, as
    # captured at discovery time, not just the short `evidence` quotes the drafting agent
    # pulled from it. Not a column on content_items itself (there is no FK-joined data on the
    # ORM object by default — see app/api/v1/content_items.py's _with_source_post, which
    # populates these via a separate batch query). Both None whenever knowledge_item_id is
    # null, or the caller didn't populate them (e.g. approve/reject/archive/mark-published's
    # response, which the frontend never re-renders the source post from).
    source_title: str | None = None
    source_body: str | None = None

    model_config = {"from_attributes": True}


class PublishAttemptResponse(BaseModel):
    id: uuid.UUID
    content_item_id: uuid.UUID
    attempt_number: int
    success: bool
    published_url: str | None
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
