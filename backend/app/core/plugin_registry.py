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
a callable `create_plugin(connection: ResolvedConnection) -> GrowthOSPlugin`. This is
deliberately a plain function, not a class the registry subclasses or special-cases — see
`plugins/dummy/` for the reference shape every real plugin should match (installed editable
as part of this project's dev environment; discovery/registry behavior against it is covered
by `backend/tests/integration/test_plugin_catalog_and_registry.py`, and its own manifest
compliance by `plugins/dummy/tests/test_contract.py`).

Credential resolution — see docs/auth/OAUTH2_ARCHITECTURE.md §1, §4: this module is the
*only* place `plugin_connections.credentials_encrypted` is ever decrypted. A plugin's
`create_plugin()` receives a `ResolvedConnection` with already-decrypted, typed
`credentials` — never ciphertext, never the raw ORM row.
"""

from __future__ import annotations

import importlib
import json
from typing import Any

import structlog
from plugins._shared.base import CapabilityNotSupported as SdkCapabilityNotSupported
from plugins._shared.base import ResolvedConnection
from plugins._shared.credentials import ApiKeyCredentials, Credentials, OAuth2Credentials
from plugins._shared.manifest import PluginManifest

from app.core.config import Settings
from app.core.crypto import derive_master_key, envelope_decrypt
from app.core.errors import CapabilityNotSupported
from app.core.plugin_catalog import PluginCatalog
from app.models.plugin import PluginCapability, PluginConnection

logger = structlog.get_logger()


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


def _resolve_credentials(
    manifest: PluginManifest, connection: PluginConnection, settings: Settings
) -> Credentials | None:
    """Decrypts `connection.credentials_encrypted` (ADR 0010's envelope) into the typed
    shape matching `manifest.auth_type`. Returns `None` if no credentials have been stored
    yet — a connection row can legitimately exist (config saved, capabilities chosen) before
    an OAuth flow has ever completed for it, or before Phase 2+ builds a credential-setting
    flow for `api_key`/`session_credentials` plugins (nothing writes
    `credentials_encrypted` for those auth types yet — out of scope for the OAuth2
    framework, see docs/reviews/OAUTH_IMPLEMENTATION_REPORT.md)."""
    if connection.credentials_encrypted is None or connection.credential_data_key_wrapped is None:
        return None

    master_key = derive_master_key(settings.credential_master_key.get_secret_value())
    plaintext = envelope_decrypt(
        master_key, connection.credentials_encrypted, connection.credential_data_key_wrapped
    )

    if manifest.auth_type == "oauth2":
        if connection.token_expires_at is None:
            logger.warning(
                "plugin_registry.oauth_credentials_missing_expiry", plugin_key=connection.plugin_key
            )
            return None
        data = json.loads(plaintext)
        return OAuth2Credentials(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            token_type=data.get("token_type", "bearer"),
            expires_at=connection.token_expires_at,
            granted_scopes=tuple(connection.granted_scopes),
        )

    if manifest.auth_type == "api_key":
        return ApiKeyCredentials(api_key=plaintext.decode("utf-8"))

    # session_credentials: no defined wire shape yet — deferred along with the rest of that
    # auth_type's connection flow.
    return None


def _load_plugin_instance(
    manifest: PluginManifest, connection: PluginConnection, settings: Settings
) -> Any:
    resolved = ResolvedConnection(
        project_id=connection.project_id,
        plugin_key=connection.plugin_key,
        label=connection.label,
        config=connection.config,
        credentials=_resolve_credentials(manifest, connection, settings),
    )

    module = importlib.import_module(f"plugins.{connection.plugin_key}.plugin")
    factory = getattr(module, "create_plugin", None)
    if factory is None:
        raise ImportError(
            f"plugins.{connection.plugin_key}.plugin must expose a "
            "create_plugin(connection) factory"
        )
    try:
        return factory(resolved)
    except SdkCapabilityNotSupported as exc:
        # A plugin's own construction code may raise the dependency-free SDK exception
        # (plugins/_shared must not import backend/app) — re-raise as the app-wide domain
        # exception at this boundary, per plugins/_shared/base.py's CapabilityNotSupported
        # docstring.
        raise CapabilityNotSupported(
            str(exc), details={"plugin_key": connection.plugin_key}
        ) from exc


class PluginRegistry:
    """Scoped to one project — constructed with that project's connections, the global
    (process-wide) PluginCatalog, and Settings (needed to derive the envelope-encryption
    master key when resolving a plugin's credentials — see `_resolve_credentials` above).
    See app/api/deps.py for where a request-scoped instance would be built (Phase 2+; no
    route needs a live plugin instance yet in Phase 1)."""

    def __init__(
        self, catalog: PluginCatalog, connections: list[PluginConnection], settings: Settings
    ) -> None:
        self._catalog = catalog
        self._connections = {c.plugin_key: c for c in connections}
        self._settings = settings

    def get(self, plugin_key: str, required: type) -> Any:
        """Resolves exactly one plugin by name, for callers that need that specific plugin
        and no substitute — e.g. an API route acting on a specific connection the user just
        picked. Deliberately fail-fast: any failure (unknown plugin, capability not
        declared/enabled, the plugin's own construction code raising) propagates as
        CapabilityNotSupported rather than being swallowed, because there is no fallback
        behavior that would make sense here — the caller asked for this plugin specifically.
        Contrast with all_with_capability() below, which is resilient by design instead. See
        docs/plugins/PLUGIN_ARCHITECTURE.md §"The registry" for both, and
        docs/reviews/PLATFORM_READINESS_REVIEW.md §3 for why this asymmetry is intentional,
        not an inconsistency."""
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

        instance = _load_plugin_instance(manifest, connection, self._settings)
        if not isinstance(instance, required):
            raise CapabilityNotSupported(
                f"Plugin {plugin_key!r}'s implementation does not structurally satisfy "
                f"{required.__name__}, despite its manifest claiming it.",
                details={"plugin_key": plugin_key, "capability": capability_name},
            )
        return instance

    def all_with_capability(self, required: type) -> list[Any]:
        """Resolves every connected, capability-enabled plugin for fan-out callers — e.g.
        conversation_finder querying every Searchable plugin without knowing plugin names in
        advance (docs/plugins/PLUGIN_ARCHITECTURE.md §"The registry"). Deliberately resilient
        by design, the opposite of get() above: one misbehaving plugin's construction code
        raising must never take down an agent run that also queries N other, healthy
        plugins — so a broken plugin is logged and skipped, not propagated. At 100+ plugins
        this matters a lot more than it does today with one fixture plugin. This is why
        get() and all_with_capability() handle the identical underlying failure differently
        on purpose, not because of an oversight — see
        docs/reviews/PLATFORM_READINESS_REVIEW.md §3."""
        capability_name = _capability_name_for_protocol(required)
        instances = []
        for plugin_key, connection in self._connections.items():
            manifest = self._catalog.get(plugin_key)
            if manifest is None or capability_name not in manifest.capabilities:
                continue
            if PluginCapability(capability_name) not in connection.capabilities_enabled:
                continue
            try:
                instance = _load_plugin_instance(manifest, connection, self._settings)
            except Exception:
                logger.warning(
                    "plugin_registry.skipped_broken_plugin",
                    plugin_key=plugin_key,
                    capability=capability_name,
                    exc_info=True,
                )
                continue
            if isinstance(instance, required):
                instances.append(instance)
        return instances


__all__ = ["PluginRegistry", "SdkCapabilityNotSupported"]
