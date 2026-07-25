"""The segmented plugin capability contract. See docs/plugins/PLUGIN_ARCHITECTURE.md and
docs/decisions/0007-plugin-discovery-and-interface-segmentation.md.

A plugin implements `GrowthOSPlugin` plus whichever of `Searchable`, `Publishable`,
`WebhookReceivable`, `MetricsQueryable` describe what it actually does — never all four,
never through one fat interface. The registry (app/core/plugin_registry.py) checks these
structurally (`isinstance` against a `Protocol`), so a plugin that doesn't implement
`Publishable` cannot be handed to code expecting one, independent of what its manifest
claims.

No plugin implementations exist in this repository yet by design — see ROADMAP.md Phase 1
("Do NOT implement: Reddit plugin ... Any plugin-specific functionality"). This module is
the contract Phase 1 proves is real (via a trivial test-fixture plugin, see
backend/tests/fixtures/dummy_plugin/), not a working integration.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from plugins._shared.manifest import PluginManifest


@dataclass(slots=True)
class PluginQuery:
    project_id: uuid.UUID
    terms: list[str]
    since: datetime | None = None
    limit: int = 25


@dataclass(slots=True)
class PluginResult:
    url: str
    title: str | None
    body: str
    author: str | None
    platform_metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class MetricsQuerySpec:
    project_id: uuid.UUID
    metric_keys: list[str]
    date_range: tuple[date, date]
    dimensions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MetricsResult:
    rows: list[dict]
    metric_keys: list[str]


@dataclass(slots=True)
class PublishResult:
    success: bool
    published_url: str | None
    error: str | None


@runtime_checkable
class Searchable(Protocol):
    async def search(self, query: PluginQuery) -> list[PluginResult]: ...


@runtime_checkable
class Publishable(Protocol):
    async def publish(self, item: object) -> PublishResult:
        """`item` is a ContentItem — typed `object` here to keep the plugin SDK free of a
        dependency on backend/app's ORM models. The publish worker (the only caller — see
        ARCHITECTURE.md §8) passes the real ContentItem."""
        ...


@runtime_checkable
class WebhookReceivable(Protocol):
    async def handle_webhook(self, payload: dict) -> None: ...


@runtime_checkable
class MetricsQueryable(Protocol):
    async def query_metrics(self, spec: MetricsQuerySpec) -> MetricsResult: ...


@runtime_checkable
class GrowthOSPlugin(Protocol):
    manifest: "PluginManifest"

    async def health_check(self) -> bool: ...


class CapabilityNotSupported(Exception):
    """Raised by the registry when a capability is requested for a plugin that doesn't
    structurally implement it. Mirrors app/core/errors.py's CapabilityNotSupported — kept
    as a separate, dependency-free exception here since plugins/_shared must not import
    backend/app. app/core/plugin_registry.py re-raises this as the app-wide domain
    exception at the boundary."""
