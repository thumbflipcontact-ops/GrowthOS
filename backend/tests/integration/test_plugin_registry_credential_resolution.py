"""Proves PluginRegistry actually decrypts plugin_connections.credentials_encrypted (ADR
0010) and hands the plugin a typed, already-decrypted ResolvedConnection.credentials — see
docs/auth/OAUTH2_ARCHITECTURE.md §1, §4 and app/core/plugin_registry.py.

Uses a small local fixture plugin (not plugins/dummy/, which is api_key-typed and doesn't
assert anything about its received connection) that echoes back whatever ResolvedConnection
it was constructed with, so these tests can assert on it directly.
"""

from __future__ import annotations

import sys
import types
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from plugins._shared.base import GrowthOSPlugin, ResolvedConnection, Searchable
from plugins._shared.credentials import ApiKeyCredentials, OAuth2Credentials
from plugins._shared.manifest import PluginManifest

from app.core.config import Settings
from app.core.crypto import derive_master_key, envelope_encrypt
from app.core.plugin_catalog import PluginCatalog
from app.core.plugin_registry import PluginRegistry
from app.models.plugin import PluginCapability, PluginConnection

_SETTINGS = Settings(
    database_url="postgresql://x:x@localhost:5432/x",
    redis_url="redis://localhost:6379/0",
    anthropic_api_key="x",
    openai_api_key="x",
    secret_key="x",
    credential_master_key="test-master-key",
)


class _EchoPlugin:
    """Records whatever ResolvedConnection it was constructed with."""

    def __init__(self, connection: ResolvedConnection) -> None:
        self.connection = connection
        self.manifest = _MANIFEST_HOLDER["manifest"]

    async def search(self, query: object) -> list:
        return []

    async def health_check(self) -> bool:
        return True


_MANIFEST_HOLDER: dict[str, PluginManifest] = {}


def _install_echo_plugin_module(plugin_key: str, manifest: PluginManifest) -> None:
    """Registers a fake `plugins.<plugin_key>.plugin` module in sys.modules so
    importlib.import_module (called by app/core/plugin_registry.py's
    _load_plugin_instance) finds it without an actual installed package — avoids the
    editable-install ceremony plugins/dummy/ needs, since this fixture only exists for this
    test module's lifetime."""
    _MANIFEST_HOLDER["manifest"] = manifest
    module_name = f"plugins.{plugin_key}.plugin"
    module = types.ModuleType(module_name)
    module.create_plugin = lambda connection: _EchoPlugin(connection)  # type: ignore[attr-defined]
    sys.modules[module_name] = module


@pytest.fixture(autouse=True)
def _cleanup_fake_modules():
    yield
    for key in list(sys.modules):
        if key.startswith("plugins.echo_"):
            del sys.modules[key]


@pytest.mark.asyncio
async def test_registry_resolves_oauth2_credentials_for_the_plugin() -> None:
    plugin_key = "echo_oauth"
    manifest = PluginManifest(
        key=plugin_key, interface_version="1.0", capabilities=("searchable",), auth_type="oauth2"
    )
    _install_echo_plugin_module(plugin_key, manifest)

    catalog = PluginCatalog()
    catalog.refresh([manifest])

    master_key = derive_master_key(_SETTINGS.credential_master_key.get_secret_value())
    import json

    payload = json.dumps(
        {"access_token": "at-123", "refresh_token": "rt-456", "token_type": "bearer"}
    ).encode()
    ciphertext, wrapped_data_key = envelope_encrypt(master_key, payload)

    expires_at = datetime.now(UTC) + timedelta(hours=1)
    connection = PluginConnection(
        project_id=uuid.uuid4(),
        plugin_key=plugin_key,
        capabilities_enabled=[PluginCapability.SEARCHABLE],
        credentials_encrypted=ciphertext,
        credential_data_key_wrapped=wrapped_data_key,
        token_expires_at=expires_at,
        granted_scopes=["read", "submit"],
    )

    registry = PluginRegistry(catalog, [connection], _SETTINGS)
    plugin = registry.get(plugin_key, Searchable)

    assert isinstance(plugin, _EchoPlugin)
    creds = plugin.connection.credentials
    assert isinstance(creds, OAuth2Credentials)
    assert creds.access_token == "at-123"
    assert creds.refresh_token == "rt-456"
    assert creds.token_type == "bearer"
    assert creds.expires_at == expires_at
    assert creds.granted_scopes == ("read", "submit")


@pytest.mark.asyncio
async def test_registry_resolves_api_key_credentials_for_the_plugin() -> None:
    plugin_key = "echo_apikey"
    manifest = PluginManifest(
        key=plugin_key, interface_version="1.0", capabilities=("searchable",), auth_type="api_key"
    )
    _install_echo_plugin_module(plugin_key, manifest)

    catalog = PluginCatalog()
    catalog.refresh([manifest])

    master_key = derive_master_key(_SETTINGS.credential_master_key.get_secret_value())
    ciphertext, wrapped_data_key = envelope_encrypt(master_key, b"the-raw-api-key")

    connection = PluginConnection(
        project_id=uuid.uuid4(),
        plugin_key=plugin_key,
        capabilities_enabled=[PluginCapability.SEARCHABLE],
        credentials_encrypted=ciphertext,
        credential_data_key_wrapped=wrapped_data_key,
    )

    registry = PluginRegistry(catalog, [connection], _SETTINGS)
    plugin = registry.get(plugin_key, Searchable)

    creds = plugin.connection.credentials
    assert isinstance(creds, ApiKeyCredentials)
    assert creds.api_key == "the-raw-api-key"


@pytest.mark.asyncio
async def test_registry_resolves_none_credentials_when_nothing_stored_yet() -> None:
    plugin_key = "echo_noauth"
    manifest = PluginManifest(
        key=plugin_key, interface_version="1.0", capabilities=("searchable",), auth_type="api_key"
    )
    _install_echo_plugin_module(plugin_key, manifest)

    catalog = PluginCatalog()
    catalog.refresh([manifest])

    connection = PluginConnection(
        project_id=uuid.uuid4(),
        plugin_key=plugin_key,
        capabilities_enabled=[PluginCapability.SEARCHABLE],
    )

    registry = PluginRegistry(catalog, [connection], _SETTINGS)
    plugin = registry.get(plugin_key, Searchable)

    assert plugin.connection.credentials is None


@pytest.mark.asyncio
async def test_registry_decrypt_fails_loudly_with_the_wrong_master_key() -> None:
    from cryptography.exceptions import InvalidTag

    plugin_key = "echo_wrongkey"
    manifest = PluginManifest(
        key=plugin_key, interface_version="1.0", capabilities=("searchable",), auth_type="api_key"
    )
    _install_echo_plugin_module(plugin_key, manifest)

    catalog = PluginCatalog()
    catalog.refresh([manifest])

    wrong_master_key = derive_master_key("a-completely-different-secret")
    ciphertext, wrapped_data_key = envelope_encrypt(wrong_master_key, b"the-raw-api-key")

    connection = PluginConnection(
        project_id=uuid.uuid4(),
        plugin_key=plugin_key,
        capabilities_enabled=[PluginCapability.SEARCHABLE],
        credentials_encrypted=ciphertext,
        credential_data_key_wrapped=wrapped_data_key,
    )

    registry = PluginRegistry(catalog, [connection], _SETTINGS)
    with pytest.raises(InvalidTag):
        registry.get(plugin_key, Searchable)


def test_resolved_connection_structurally_satisfies_growthos_plugin_via_echo() -> None:
    # Sanity check that _EchoPlugin (the test fixture above) is a legitimate GrowthOSPlugin —
    # if this ever stops being true the other tests in this file would be testing nothing.
    manifest = PluginManifest(key="x", interface_version="1.0", capabilities=("searchable",))
    _MANIFEST_HOLDER["manifest"] = manifest
    plugin = _EchoPlugin(
        ResolvedConnection(
            project_id=uuid.uuid4(), plugin_key="x", label="default", config={}, credentials=None
        )
    )
    assert isinstance(plugin, GrowthOSPlugin)
