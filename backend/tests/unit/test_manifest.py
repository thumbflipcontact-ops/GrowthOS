"""See docs/plugins/PLUGIN_ARCHITECTURE.md."""

from __future__ import annotations

import pytest
from plugins._shared.manifest import ContentTypeSpec, PluginManifest
from pydantic import BaseModel


class _Config(BaseModel):
    api_key: str
    subreddits: list[str] = []


def test_manifest_generates_json_schema_from_config_model() -> None:
    manifest = PluginManifest(
        key="example",
        interface_version="1.0",
        capabilities=("searchable", "publishable"),
        content_types=(ContentTypeSpec(key="example_reply", max_length=280),),
        config_schema=_Config,
    )
    schema = manifest.config_json_schema()
    assert schema["type"] == "object"
    assert "api_key" in schema["properties"]


def test_manifest_with_no_config_schema_returns_empty_object_schema() -> None:
    manifest = PluginManifest(key="example", interface_version="1.0", capabilities=("searchable",))
    assert manifest.config_json_schema() == {"type": "object", "properties": {}}


def test_manifest_is_immutable() -> None:
    manifest = PluginManifest(key="example", interface_version="1.0", capabilities=("searchable",))
    with pytest.raises(AttributeError):
        manifest.key = "changed"  # type: ignore[misc]
