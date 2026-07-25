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

from app.core.errors import CapabilityNotSupported
from app.core.plugin_catalog import (
    PluginCatalog,
    discover_installed_plugins,
    sync_catalog_to_db,
)
from app.core.plugin_registry import PluginRegistry
from app.models.plugin import PluginCapability, PluginConnection

pytestmark = pytest.mark.integration


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
    registry = PluginRegistry(catalog, [connection])

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
    registry = PluginRegistry(catalog, [connection])

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
    registry = PluginRegistry(catalog, [connection])

    with pytest.raises(CapabilityNotSupported):
        registry.get("dummy", Searchable)


@pytest.mark.asyncio
async def test_registry_rejects_unknown_plugin_key() -> None:
    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    registry = PluginRegistry(catalog, connections=[])

    with pytest.raises(CapabilityNotSupported):
        registry.get("not-a-real-plugin", Searchable)


@pytest.mark.asyncio
async def test_registry_all_with_capability_filters_correctly() -> None:
    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    connection = PluginConnection(
        project_id=uuid.uuid4(), plugin_key="dummy", capabilities_enabled=[PluginCapability.SEARCHABLE]
    )
    registry = PluginRegistry(catalog, [connection])

    assert len(registry.all_with_capability(Searchable)) == 1
    assert len(registry.all_with_capability(MetricsQueryable)) == 0
