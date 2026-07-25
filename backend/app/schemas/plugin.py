from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PluginCatalogEntryResponse(BaseModel):
    plugin_key: str
    interface_version: str
    capabilities: list[str]
    content_types: list[dict]
    config_schema: dict
    auth_type: str

    model_config = {"from_attributes": True}


class CreatePluginConnectionRequest(BaseModel):
    """See docs/api/API_DESIGN.md and PluginConnectionService. `config` is validated against
    the target plugin's `config_schema` (a pydantic model, checked server-side — not just the
    JSON Schema the frontend renders from `config_json_schema()`) before the connection is
    created. Credentials are deliberately not part of this request — see
    docs/plugins/PLUGIN_ARCHITECTURE.md §Credentials; wiring a connection's actual credentials
    is a separate, auth-type-specific flow, out of scope here."""

    plugin_key: str = Field(min_length=1)
    config: dict = Field(default_factory=dict)
    capabilities_enabled: list[str] = Field(default_factory=list)
    # Disambiguates multiple connections to the same plugin within one project — see
    # docs/auth/OAUTH2_ARCHITECTURE.md §2. "default" covers the common one-connection case.
    label: str = Field(default="default", min_length=1)


class PluginConnectionResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    plugin_key: str
    label: str
    capabilities_enabled: list[str]
    config: dict
    status: str
    last_checked_at: datetime | None
    # Plaintext, deliberately — neither is a credential; see
    # docs/auth/OAUTH2_ARCHITECTURE.md §2. Always null for a non-OAuth connection.
    token_expires_at: datetime | None
    granted_scopes: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OAuthStartRequest(BaseModel):
    """See docs/auth/OAUTH2_ARCHITECTURE.md §3. `label` lets a project connect a second
    account to the same OAuth-capable plugin instead of always targeting "default"."""

    label: str = Field(default="default", min_length=1)


class OAuthStartResponse(BaseModel):
    authorize_url: str
