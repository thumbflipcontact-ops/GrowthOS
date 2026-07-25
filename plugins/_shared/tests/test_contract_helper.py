"""Tests the contract-checking helper itself (test_plugin_contract.py) against fake plugin
instances — proving assert_plugin_contract catches exactly the mismatches it claims to."""

from __future__ import annotations

import pytest

from plugins._shared.manifest import PluginManifest
from plugins._shared.oauth import OAuthProviderSpec
from plugins._shared.tests.test_plugin_contract import PluginContractError, assert_plugin_contract

MANIFEST = PluginManifest(key="fake", interface_version="1.0", capabilities=("searchable",))

OAUTH_MANIFEST_NO_SPEC = PluginManifest(
    key="fake-oauth",
    interface_version="1.0",
    capabilities=("searchable",),
    auth_type="oauth2",
)

OAUTH_MANIFEST_WITH_SPEC = PluginManifest(
    key="fake-oauth",
    interface_version="1.0",
    capabilities=("searchable",),
    auth_type="oauth2",
    oauth=OAuthProviderSpec(
        authorize_url="https://example.invalid/authorize", token_url="https://example.invalid/token"
    ),
)


class _HonestPlugin:
    manifest = MANIFEST

    async def search(self, query: object) -> list:
        return []

    async def health_check(self) -> bool:
        return True


class _LyingPlugin:
    """Declares `searchable` but doesn't implement `search()`."""

    manifest = MANIFEST

    async def health_check(self) -> bool:
        return True


class _BrokenHealthCheck:
    manifest = MANIFEST

    async def search(self, query: object) -> list:
        return []

    async def health_check(self) -> str:  # wrong return type
        return "yes"


def test_accepts_a_plugin_that_honors_its_manifest() -> None:
    assert_plugin_contract(_HonestPlugin())


def test_rejects_a_plugin_missing_a_declared_capability() -> None:
    with pytest.raises(PluginContractError):
        assert_plugin_contract(_LyingPlugin())


def test_rejects_a_health_check_with_the_wrong_return_type() -> None:
    with pytest.raises(PluginContractError):
        assert_plugin_contract(_BrokenHealthCheck())


def test_rejects_something_that_is_not_a_plugin_at_all() -> None:
    with pytest.raises(PluginContractError):
        assert_plugin_contract(object())


class _OAuthPluginMissingSpec:
    manifest = OAUTH_MANIFEST_NO_SPEC

    async def search(self, query: object) -> list:
        return []

    async def health_check(self) -> bool:
        return True


class _OAuthPluginWithSpec:
    manifest = OAUTH_MANIFEST_WITH_SPEC

    async def search(self, query: object) -> list:
        return []

    async def health_check(self) -> bool:
        return True


def test_rejects_oauth2_manifest_missing_oauth_spec() -> None:
    with pytest.raises(PluginContractError):
        assert_plugin_contract(_OAuthPluginMissingSpec())


def test_accepts_oauth2_manifest_with_a_valid_spec() -> None:
    assert_plugin_contract(_OAuthPluginWithSpec())
