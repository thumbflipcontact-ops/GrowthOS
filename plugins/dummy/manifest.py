"""Phase 1 test fixture — see README.md. Not a real plugin."""

from pydantic import BaseModel

from plugins._shared.manifest import ContentTypeSpec, PluginManifest


class DummyConnectionConfig(BaseModel):
    greeting: str = "hello"


MANIFEST = PluginManifest(
    key="dummy",
    interface_version="1.0",
    capabilities=("searchable",),
    content_types=(ContentTypeSpec(key="dummy_reply", max_length=280),),
    config_schema=DummyConnectionConfig,
    auth_type="api_key",
)
