"""End-to-end proof that plugin discovery works via REAL `importlib.metadata` entry points
— not just an injectable list — using the `dummy` test-fixture plugin (plugins/dummy/, pip
installed editable as part of this project's dev environment). See
docs/plugins/PLUGIN_ARCHITECTURE.md and docs/decisions/0007.

This is the concrete exit check docs/architecture/archive/MIGRATION_V1_TO_V2.md Step 2
specified: "a trivial hello world plugin package with a manifest and no real API calls can
be installed, discovered at startup... before Reddit-specific code exists at all."
"""

from __future__ import annotations

import uuid

import pytest
from plugins._shared.base import MetricsQueryable, PluginQuery, Publishable, Searchable
from plugins._shared.manifest import PluginManifest

from app.core.config import Settings
from app.core.errors import CapabilityNotSupported
from app.core.plugin_catalog import (
    PluginCatalog,
    discover_installed_plugins,
    sync_catalog_to_db,
)
from app.core.plugin_registry import PluginRegistry
from app.models.plugin import PluginCapability, PluginConnection, PluginConnectionStatus

pytestmark = pytest.mark.integration

# Built directly (not via get_settings(), which needs DATABASE_URL — only set once the
# postgres_url fixture actually runs, not at module import time) — none of these tests touch
# the database or decrypt real credentials, so placeholder values are enough. Matches
# test_config.py's _base_env() pattern.
_SETTINGS = Settings(
    database_url="postgresql://x:x@localhost:5432/x",
    redis_url="redis://localhost:6379/0",
    anthropic_api_key="x",
    openai_api_key="x",
    secret_key="x",
    credential_master_key="x",
)


def test_discover_installed_plugins_finds_the_dummy_fixture() -> None:
    manifests = discover_installed_plugins()
    keys = {m.key for m in manifests}
    assert "dummy" in keys
    dummy = next(m for m in manifests if m.key == "dummy")
    assert dummy.capabilities == ("searchable",)


def test_catalog_refresh_is_a_full_replace() -> None:
    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    assert catalog.get("dummy") is not None

    catalog.refresh([])  # simulate a process restart where the plugin was uninstalled
    assert catalog.get("dummy") is None


@pytest.mark.asyncio
async def test_sync_catalog_to_db_persists_discovered_manifests(db_session) -> None:
    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    await sync_catalog_to_db(db_session, catalog)

    from app.repositories.plugin_repository import PluginCatalogRepository

    entries = await PluginCatalogRepository(db_session).list_all()
    assert any(e.plugin_key == "dummy" for e in entries)


@pytest.mark.asyncio
async def test_registry_resolves_a_capability_the_plugin_declares() -> None:
    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    connection = PluginConnection(
        project_id=uuid.uuid4(), plugin_key="dummy", capabilities_enabled=[PluginCapability.SEARCHABLE]
    )
    registry = PluginRegistry(catalog, [connection], _SETTINGS)

    plugin = registry.get("dummy", Searchable)
    results = await plugin.search(PluginQuery(project_id=connection.project_id, terms=["test"]))
    assert len(results) == 1


@pytest.mark.asyncio
async def test_registry_rejects_capability_the_manifest_does_not_declare() -> None:
    """Gate 1: code-level. The dummy plugin's manifest only declares `searchable`."""
    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    connection = PluginConnection(
        project_id=uuid.uuid4(), plugin_key="dummy", capabilities_enabled=[PluginCapability.SEARCHABLE]
    )
    registry = PluginRegistry(catalog, [connection], _SETTINGS)

    with pytest.raises(CapabilityNotSupported):
        registry.get("dummy", Publishable)


@pytest.mark.asyncio
async def test_registry_rejects_capability_project_has_not_enabled() -> None:
    """Gate 2: data-level. Even though nothing about `searchable` vs another capability is
    at issue here, the project's connection simply hasn't turned it on — see
    docs/plugins/PLUGIN_ARCHITECTURE.md "Two independent gates"."""
    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    connection = PluginConnection(
        project_id=uuid.uuid4(), plugin_key="dummy", capabilities_enabled=[]  # nothing enabled
    )
    registry = PluginRegistry(catalog, [connection], _SETTINGS)

    with pytest.raises(CapabilityNotSupported):
        registry.get("dummy", Searchable)


@pytest.mark.asyncio
async def test_registry_rejects_unknown_plugin_key() -> None:
    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    registry = PluginRegistry(catalog, connections=[], settings=_SETTINGS)

    with pytest.raises(CapabilityNotSupported):
        registry.get("not-a-real-plugin", Searchable)


@pytest.mark.asyncio
async def test_registry_get_propagates_a_broken_plugins_construction_error() -> None:
    """get() is fail-fast: a plugin that declares a capability, is enabled, but whose own
    create_plugin() blows up (here: the module doesn't even exist) raises rather than being
    silently swallowed — see plugin_registry.py's get() docstring."""
    catalog = PluginCatalog()
    catalog.refresh(
        [
            *discover_installed_plugins(),
            _broken_manifest(),
        ]
    )
    connection = PluginConnection(
        project_id=uuid.uuid4(),
        plugin_key="broken",
        capabilities_enabled=[PluginCapability.SEARCHABLE],
    )
    registry = PluginRegistry(catalog, [connection], _SETTINGS)

    with pytest.raises(ModuleNotFoundError):
        registry.get("broken", Searchable)


@pytest.mark.asyncio
async def test_registry_all_with_capability_skips_a_broken_plugin_but_returns_the_rest() -> None:
    """all_with_capability() is resilient by design: the same broken plugin as above must not
    prevent the healthy `dummy` plugin from being returned alongside it — see
    plugin_registry.py's all_with_capability() docstring."""
    catalog = PluginCatalog()
    catalog.refresh(
        [
            *discover_installed_plugins(),
            _broken_manifest(),
        ]
    )
    dummy_connection = PluginConnection(
        project_id=uuid.uuid4(),
        plugin_key="dummy",
        capabilities_enabled=[PluginCapability.SEARCHABLE],
        status=PluginConnectionStatus.CONNECTED,
    )
    broken_connection = PluginConnection(
        project_id=dummy_connection.project_id,
        plugin_key="broken",
        capabilities_enabled=[PluginCapability.SEARCHABLE],
        status=PluginConnectionStatus.CONNECTED,
    )
    registry = PluginRegistry(catalog, [dummy_connection, broken_connection], _SETTINGS)

    results = registry.all_with_capability(Searchable)
    assert len(results) == 1  # only dummy — broken was skipped, not raised


def _broken_manifest() -> PluginManifest:
    return PluginManifest(key="broken", interface_version="1.0", capabilities=("searchable",))


@pytest.mark.asyncio
async def test_registry_all_with_capability_filters_correctly() -> None:
    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    connection = PluginConnection(
        project_id=uuid.uuid4(),
        plugin_key="dummy",
        capabilities_enabled=[PluginCapability.SEARCHABLE],
        status=PluginConnectionStatus.CONNECTED,
    )
    registry = PluginRegistry(catalog, [connection], _SETTINGS)

    assert len(registry.all_with_capability(Searchable)) == 1
    assert len(registry.all_with_capability(MetricsQueryable)) == 0


@pytest.mark.asyncio
async def test_registry_all_with_capability_excludes_a_disconnected_connection() -> None:
    """A connection row can outlive an actually-working connection (OAuth never completed,
    later disconnected, token permanently expired) — all_with_capability() must not fan out
    to it, unlike a merely broken-but-CONNECTED plugin (see the "skips a broken plugin" test
    above, which is a different failure mode: constructible-but-erroring vs never-connected)."""
    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    connection = PluginConnection(
        project_id=uuid.uuid4(),
        plugin_key="dummy",
        capabilities_enabled=[PluginCapability.SEARCHABLE],
        status=PluginConnectionStatus.DISCONNECTED,
    )
    registry = PluginRegistry(catalog, [connection], _SETTINGS)

    assert registry.all_with_capability(Searchable) == []
