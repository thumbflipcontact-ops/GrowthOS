from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AgentConfigUpsertRequest(BaseModel):
    """See app/services/agent_config.py. `config` is validated server-side against the
    target agent's own `config_schema` before the row is written — not just accepted as-is."""

    config: dict = Field(default_factory=dict)
    schedule_cron: str | None = None
    enabled: bool = True


class AgentConfigResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    agent_key: str
    config: dict
    schedule_cron: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentTriggerResponse(BaseModel):
    agent_config_id: uuid.UUID
    agent_key: str
    status: str = "queued"


class AgentRunResponse(BaseModel):
    id: uuid.UUID
    agent_config_id: uuid.UUID
    project_id: uuid.UUID
    agent_key: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    summary: dict | None
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentRunListResponse(BaseModel):
    """`total` is the full row count for this (project, agent_key) — independent of `limit`/
    `offset` — so the frontend can compute page count without fetching every row."""

    runs: list[AgentRunResponse]
    total: int
