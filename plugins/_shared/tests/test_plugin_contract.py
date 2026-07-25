"""The shared plugin contract test suite — CONTRIBUTING.md's "Adding a new plugin" step 5 and
docs/plugins/PLUGIN_ARCHITECTURE.md's "How to add a new plugin" both point here. This is not
a file pytest collects and runs on its own (it defines no `test_*` functions at module level);
it's a small library a plugin's own test suite imports and calls against its own plugin
instance. This keeps the check runnable per-plugin, in each plugin's own `tests/` folder, per
CONTRIBUTING.md's "every agent and plugin ships with its own test suite in its own folder."

Usage, from `plugins/<name>/tests/test_contract.py`:

    from plugins._shared.tests.test_plugin_contract import assert_plugin_contract
    from plugins.<name>.plugin import create_plugin
    from plugins.<name>.manifest import MANIFEST

    def test_plugin_honors_its_manifest() -> None:
        assert_plugin_contract(create_plugin(fake_connection))

Deliberately dependency-free (only stdlib + plugins/_shared itself): a plugin author should
not need pytest installed just to import this module, even though in practice they'll be
calling it from inside a pytest test.
"""

from __future__ import annotations

import asyncio

from plugins._shared.base import (
    GrowthOSPlugin,
    MetricsQueryable,
    Publishable,
    Searchable,
    WebhookReceivable,
)
from plugins._shared.manifest import PluginManifest

CAPABILITY_PROTOCOLS: dict[str, type] = {
    "searchable": Searchable,
    "publishable": Publishable,
    "webhook_receivable": WebhookReceivable,
    "metrics_queryable": MetricsQueryable,
}


class PluginContractError(AssertionError):
    """Raised (as a plain AssertionError subclass, so pytest reports it like any other failed
    assertion) when a plugin instance doesn't honor its own manifest."""


def assert_plugin_contract(plugin: object) -> None:
    """Verifies `plugin`:

    1. Structurally implements `GrowthOSPlugin` (a `manifest` attribute + `health_check()`).
    2. Has a `manifest` that is a real `PluginManifest` with a non-empty `key` and
       `interface_version`.
    3. Structurally implements every capability Protocol its manifest declares — this is
       exactly the check `PluginRegistry` performs at request time (see
       app/core/plugin_registry.py), run here at test time instead, so a manifest that lies
       about what the plugin implements fails in CI, not in production.
    4. `health_check()` actually runs and returns a `bool`.

    Does NOT call `search()`/`publish()`/etc. — those have real side effects (network calls)
    and plugin-specific inputs this shared suite has no way to construct generically. Test
    those yourself, in your own plugin's test suite.
    """
    if not isinstance(plugin, GrowthOSPlugin):
        raise PluginContractError(
            f"{plugin!r} does not structurally implement GrowthOSPlugin — it needs a "
            "`manifest` attribute and an async `health_check()` method."
        )

    manifest = plugin.manifest
    if not isinstance(manifest, PluginManifest):
        raise PluginContractError(
            f"{plugin!r}.manifest is {manifest!r}, not a plugins._shared.manifest.PluginManifest."
        )
    if not manifest.key:
        raise PluginContractError("manifest.key must be a non-empty string.")
    if not manifest.interface_version:
        raise PluginContractError("manifest.interface_version must be a non-empty string.")

    if manifest.auth_type == "oauth2":
        # See docs/auth/OAUTH2_ARCHITECTURE.md §4 — an oauth2 plugin with no OAuthProviderSpec
        # would pass every other check here and then fail at the first real connection
        # attempt; catch it at test time instead. Mirrors plugin_catalog.py's discovery-time
        # check (app/core/plugin_catalog.py), run here so a plugin author sees it in their own
        # test suite, not just at process startup.
        if manifest.oauth is None:
            raise PluginContractError(
                'manifest.auth_type == "oauth2" but manifest.oauth is None — declare an '
                "OAuthProviderSpec (plugins._shared.oauth)."
            )
        if not manifest.oauth.authorize_url or not manifest.oauth.token_url:
            raise PluginContractError(
                "manifest.oauth must declare non-empty authorize_url and token_url."
            )

    for capability in manifest.capabilities:
        protocol = CAPABILITY_PROTOCOLS[capability]
        if not isinstance(plugin, protocol):
            raise PluginContractError(
                f"manifest declares capability {capability!r} but {plugin!r} does not "
                f"structurally implement {protocol.__name__} — implement the missing "
                "method(s), or remove the capability from the manifest if it isn't real yet."
            )

    result = asyncio.run(plugin.health_check())
    if not isinstance(result, bool):
        raise PluginContractError(
            f"health_check() must return a bool, got {result!r} ({type(result).__name__})."
        )


__all__ = ["CAPABILITY_PROTOCOLS", "PluginContractError", "assert_plugin_contract"]
