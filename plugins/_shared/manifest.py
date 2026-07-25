"""The plugin manifest — how a plugin describes itself to the core system. See
docs/plugins/PLUGIN_ARCHITECTURE.md and docs/decisions/0007-plugin-discovery-and-interface-segmentation.md.

A plugin package exposes a module-level `MANIFEST: PluginManifest` (conventionally in
`plugins/<name>/manifest.py`), discovered via the `growthos.plugins` entry point group — see
app/core/plugin_catalog.py. Nothing about this module depends on FastAPI, SQLAlchemy, or any
other backend concern: it is the contract plugin authors write against, and it must stay
importable with zero heavyweight dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

# The complete, closed set of capability kinds a plugin can implement — see
# plugins/_shared/base.py. A plugin doesn't invent new capability kinds, only a new
# combination of these four (docs/database/SCHEMA.md's core-owned-taxonomy rule).
PluginCapabilityName = Literal["searchable", "publishable", "webhook_receivable", "metrics_queryable"]

AuthType = Literal["oauth2", "api_key", "session_credentials"]


@dataclass(frozen=True, slots=True)
class ContentTypeSpec:
    """One kind of content a Publishable plugin can publish — see
    docs/decisions/0008-plugin-contributed-content-types.md. `key` is what
    content_items.type actually stores; it is validated against the union of every
    installed plugin's ContentTypeSpecs, never a fixed database enum."""

    key: str
    max_length: int | None = None
    publish_target: str | None = None  # a human-readable hint, e.g. "thread", "message"


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """The complete, machine-readable description of a plugin. See
    docs/plugins/PLUGIN_ARCHITECTURE.md's manifest example."""

    key: str
    interface_version: str
    capabilities: tuple[PluginCapabilityName, ...]
    content_types: tuple[ContentTypeSpec, ...] = field(default_factory=tuple)
    config_schema: type[BaseModel] | None = None
    auth_type: AuthType = "api_key"

    def config_json_schema(self) -> dict:
        """The JSON Schema the frontend's DynamicConnectionForm renders — see
        docs/decisions/0009-plugin-config-schema-dynamic-ui.md. A plugin with no
        connection-time configuration (rare, but valid) has an empty object schema."""
        if self.config_schema is None:
            return {"type": "object", "properties": {}}
        return self.config_schema.model_json_schema()
