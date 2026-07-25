"""The per-project plugin registry. See docs/plugins/PLUGIN_ARCHITECTURE.md §"The registry".

Agents ask for a *capability Protocol*, not a plugin by name, wherever possible — this is
what lets agent code stay unchanged as new plugins are connected. Every lookup passes
through two independent gates before a plugin instance is even constructed:

1. Code-level: does the plugin's manifest declare this capability at all?
2. Data-level: has this project's connection enabled this capability?
   (`plugin_connections.capabilities_enabled` — a project can hold valid
   publish-capable credentials and still have publishing turned off.)

Only after both gates pass does the registry construct the plugin instance and perform a
third, structural check (`isinstance` against the capability Protocol) — defense in depth
against a manifest that lies about what it implements.

Convention for locating a plugin's implementation: `plugins.<plugin_key>.plugin` must expose
a callable `create_plugin(connection) -> GrowthOSPlugin`. This is deliberately a plain
function, not a class the registry subclasses or special-cases — see
backend/tests/fixtures/dummy_plugin for the reference shape every real plugin should match.
"""

from __future__ import annotations

import importlib
from typing import Any

from plugins._shared.base import CapabilityNotSupported as SdkCapabilityNotSupported

from app.core.errors import CapabilityNotSupported
from app.core.plugin_catalog import PluginCatalog
from app.models.plugin import PluginCapability, PluginConnection


def _capability_name_for_protocol(protocol: type) -> str:
    name = getattr(protocol, "__name__", "")
    mapping = {
        "Searchable": "searchable",
        "Publishable": "publishable",
        "WebhookReceivable": "webhook_receivable",
        "MetricsQueryable": "metrics_queryable",
    }
    if name not in mapping:
        raise ValueError(f"{name!r} is not one of the plugin capability Protocols")
    return mapping[name]


def _load_plugin_instance(plugin_key: str, connection: PluginConnection) -> Any:
    module = importlib.import_module(f"plugins.{plugin_key}.plugin")
    factory = getattr(module, "create_plugin", None)
    if factory is None:
        raise ImportError(
            f"plugins.{plugin_key}.plugin must expose a create_plugin(connection) factory"
        )
    try:
        return factory(connection)
    except SdkCapabilityNotSupported as exc:
        # A plugin's own construction code may raise the dependency-free SDK exception
        # (plugins/_shared must not import backend/app) — re-raise as the app-wide domain
        # exception at this boundary, per plugins/_shared/base.py's CapabilityNotSupported
        # docstring.
        raise CapabilityNotSupported(str(exc), details={"plugin_key": plugin_key}) from exc


class PluginRegistry:
    """Scoped to one project — constructed with that project's connections and the global
    (process-wide) PluginCatalog. See app/api/deps.py for where a request-scoped instance
    would be built (Phase 2+; no route needs a live plugin instance yet in Phase 1)."""

    def __init__(self, catalog: PluginCatalog, connections: list[PluginConnection]) -> None:
        self._catalog = catalog
        self._connections = {c.plugin_key: c for c in connections}

    def get(self, plugin_key: str, required: type) -> Any:
        capability_name = _capability_name_for_protocol(required)

        connection = self._connections.get(plugin_key)
        if connection is None:
            raise CapabilityNotSupported(
                f"Project has no connection for plugin {plugin_key!r}.",
                details={"plugin_key": plugin_key},
            )

        manifest = self._catalog.get(plugin_key)
        if manifest is None or capability_name not in manifest.capabilities:
            raise CapabilityNotSupported(
                f"Plugin {plugin_key!r} does not implement {required.__name__}.",
                details={"plugin_key": plugin_key, "capability": capability_name},
            )

        if PluginCapability(capability_name) not in connection.capabilities_enabled:
            raise CapabilityNotSupported(
                f"Project has not enabled {required.__name__} for plugin {plugin_key!r}.",
                details={"plugin_key": plugin_key, "capability": capability_name},
            )

        instance = _load_plugin_instance(plugin_key, connection)
        if not isinstance(instance, required):
            raise CapabilityNotSupported(
                f"Plugin {plugin_key!r}'s implementation does not structurally satisfy "
                f"{required.__name__}, despite its manifest claiming it.",
                details={"plugin_key": plugin_key, "capability": capability_name},
            )
        return instance

    def all_with_capability(self, required: type) -> list[Any]:
        capability_name = _capability_name_for_protocol(required)
        instances = []
        for plugin_key, connection in self._connections.items():
            manifest = self._catalog.get(plugin_key)
            if manifest is None or capability_name not in manifest.capabilities:
                continue
            if PluginCapability(capability_name) not in connection.capabilities_enabled:
                continue
            try:
                instance = _load_plugin_instance(plugin_key, connection)
            except Exception:
                continue
            if isinstance(instance, required):
                instances.append(instance)
        return instances


__all__ = ["PluginRegistry", "SdkCapabilityNotSupported"]
