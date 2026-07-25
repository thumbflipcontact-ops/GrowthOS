"""Proves the segmented capability Protocols are structurally checked, not just declared —
see docs/plugins/PLUGIN_ARCHITECTURE.md and docs/decisions/0007."""

from __future__ import annotations

from plugins._shared.base import MetricsQueryable, Publishable, Searchable, WebhookReceivable


class _SearchOnlyPlugin:
    async def search(self, query):
        return []

    async def health_check(self) -> bool:
        return True


class _FullPlugin:
    async def search(self, query):
        return []

    async def publish(self, item):
        return None

    async def handle_webhook(self, payload):
        return None

    async def query_metrics(self, spec):
        return None

    async def health_check(self) -> bool:
        return True


def test_plugin_implementing_only_search_satisfies_only_searchable() -> None:
    plugin = _SearchOnlyPlugin()
    assert isinstance(plugin, Searchable)
    assert not isinstance(plugin, Publishable)
    assert not isinstance(plugin, WebhookReceivable)
    assert not isinstance(plugin, MetricsQueryable)


def test_plugin_implementing_all_four_satisfies_all_four() -> None:
    plugin = _FullPlugin()
    assert isinstance(plugin, Searchable)
    assert isinstance(plugin, Publishable)
    assert isinstance(plugin, WebhookReceivable)
    assert isinstance(plugin, MetricsQueryable)
