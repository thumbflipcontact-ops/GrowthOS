from __future__ import annotations

from pydantic import BaseModel


class PluginCatalogEntryResponse(BaseModel):
    plugin_key: str
    interface_version: str
    capabilities: list[str]
    content_types: list[dict]
    config_schema: dict
    auth_type: str

    model_config = {"from_attributes": True}
