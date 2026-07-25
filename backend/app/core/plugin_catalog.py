"""The plugin catalog scanner. See docs/plugins/PLUGIN_ARCHITECTURE.md §Discovery and
docs/decisions/0007-plugin-discovery-and-interface-segmentation.md.

Discovery is a *scanner*, never a hand-maintained list: every installed plugin package
declares an entry point in the `growthos.plugins` group, pointing at its manifest. Adding a
plugin means installing a package with that entry point — nothing here changes.

    # a plugin's pyproject.toml
    [project.entry-points."growthos.plugins"]
    reddit = "plugins.reddit.manifest:MANIFEST"
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Iterable, Sequence

import structlog
from plugins._shared.manifest import PluginManifest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

ENTRY_POINT_GROUP = "growthos.plugins"

# The interface version(s) this running core supports. A discovered plugin manifest
# declaring a version outside this set fails discovery loudly (logged, excluded from the
# catalog) rather than being silently loaded — see
# docs/plugins/PLUGIN_ARCHITECTURE.md §Interface versioning.
SUPPORTED_INTERFACE_VERSIONS = frozenset({"1.0"})


def discover_installed_plugins() -> list[PluginManifest]:
    """Scans installed packages for `growthos.plugins` entry points and loads each
    manifest. A plugin that fails to import, doesn't expose a real PluginManifest, or
    declares an unsupported interface_version is logged and excluded — one bad plugin
    package must never prevent the rest of the catalog (and the whole application) from
    starting."""
    manifests: list[PluginManifest] = []
    for entry_point in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            candidate = entry_point.load()
        except Exception:
            logger.error(
                "plugin_discovery.import_failed", plugin_key=entry_point.name, exc_info=True
            )
            continue

        if not isinstance(candidate, PluginManifest):
            logger.error(
                "plugin_discovery.invalid_manifest",
                plugin_key=entry_point.name,
                got=type(candidate).__name__,
            )
            continue

        if candidate.interface_version not in SUPPORTED_INTERFACE_VERSIONS:
            logger.error(
                "plugin_discovery.unsupported_interface_version",
                plugin_key=candidate.key,
                declared=candidate.interface_version,
                supported=sorted(SUPPORTED_INTERFACE_VERSIONS),
            )
            continue

        manifests.append(candidate)

    return manifests


class PluginCatalog:
    """In-process, read-mostly registry of every discovered plugin manifest — built once at
    startup (see app/main.py's lifespan) and used by PluginRegistry to resolve capabilities.
    Refreshing is always a full replace, matching "refreshed wholesale on each process
    start" (docs/plugins/PLUGIN_ARCHITECTURE.md), never an incremental patch."""

    def __init__(self) -> None:
        self._manifests: dict[str, PluginManifest] = {}

    def refresh(self, manifests: Iterable[PluginManifest]) -> None:
        self._manifests = {m.key: m for m in manifests}

    def get(self, plugin_key: str) -> PluginManifest | None:
        return self._manifests.get(plugin_key)

    def all(self) -> Sequence[PluginManifest]:
        return tuple(self._manifests.values())


async def sync_catalog_to_db(session: AsyncSession, catalog: PluginCatalog) -> None:
    """Mirrors the in-process catalog into the `plugin_catalog` table so the API/frontend
    can query "what plugins exist" without importing plugin Python code — see
    docs/database/SCHEMA.md's plugin_catalog note. Called once at startup, after
    `catalog.refresh(...)`. A full delete-and-reinsert, consistent with the catalog being
    rebuilt wholesale, not patched, on every process start."""
    from app.models.plugin import PluginCatalogEntry

    await session.execute(delete(PluginCatalogEntry))
    for manifest in catalog.all():
        session.add(
            PluginCatalogEntry(
                plugin_key=manifest.key,
                interface_version=manifest.interface_version,
                capabilities=list(manifest.capabilities),
                content_types=[
                    {
                        "key": ct.key,
                        "max_length": ct.max_length,
                        "publish_target": ct.publish_target,
                    }
                    for ct in manifest.content_types
                ],
                config_schema=manifest.config_json_schema(),
                auth_type=manifest.auth_type,
            )
        )
    await session.commit()
