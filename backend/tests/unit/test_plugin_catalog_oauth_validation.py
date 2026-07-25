"""See docs/auth/OAUTH2_ARCHITECTURE.md §4 — plugin_catalog.py's discovery step rejects an
oauth2 manifest with no OAuthProviderSpec, the same way it rejects an unsupported
interface_version. Uses a monkeypatched entry_points() rather than a real installed package,
mirroring how backend/tests/integration/test_plugin_catalog_and_registry.py exercises
discovery against the real `dummy` fixture — this test only needs a fake manifest, not a real
package."""

from __future__ import annotations

import importlib.metadata

from plugins._shared.manifest import PluginManifest
from plugins._shared.oauth import OAuthProviderSpec

from app.core import plugin_catalog


class _FakeEntryPoint:
    def __init__(self, name: str, manifest: PluginManifest) -> None:
        self.name = name
        self._manifest = manifest

    def load(self) -> PluginManifest:
        return self._manifest


def test_discover_rejects_oauth2_manifest_with_no_oauth_spec(monkeypatch) -> None:
    bad = PluginManifest(
        key="bad-oauth",
        interface_version="1.0",
        capabilities=("searchable",),
        auth_type="oauth2",
        oauth=None,
    )
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda group=None: [_FakeEntryPoint("bad-oauth", bad)],
    )
    manifests = plugin_catalog.discover_installed_plugins()
    assert manifests == []


def test_discover_accepts_oauth2_manifest_with_a_valid_spec(monkeypatch) -> None:
    good = PluginManifest(
        key="good-oauth",
        interface_version="1.0",
        capabilities=("searchable",),
        auth_type="oauth2",
        oauth=OAuthProviderSpec(
            authorize_url="https://example.invalid/authorize", token_url="https://example.invalid/token"
        ),
    )
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda group=None: [_FakeEntryPoint("good-oauth", good)],
    )
    manifests = plugin_catalog.discover_installed_plugins()
    assert [m.key for m in manifests] == ["good-oauth"]


def test_discover_still_accepts_non_oauth2_manifests(monkeypatch) -> None:
    fine = PluginManifest(
        key="fine", interface_version="1.0", capabilities=("searchable",), auth_type="api_key"
    )
    monkeypatch.setattr(
        importlib.metadata, "entry_points", lambda group=None: [_FakeEntryPoint("fine", fine)]
    )
    manifests = plugin_catalog.discover_installed_plugins()
    assert [m.key for m in manifests] == ["fine"]
