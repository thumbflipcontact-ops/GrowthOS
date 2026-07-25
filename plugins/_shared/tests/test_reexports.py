"""Proves plugins/_shared/__init__.py's re-exports actually resolve to the same objects as
importing from the submodules directly — a stale re-export (renamed in one place, not the
other) would otherwise go unnoticed until a plugin author hit an ImportError."""

from __future__ import annotations

from plugins import _shared
from plugins._shared import base, events, manifest, rate_limit


def test_reexports_are_the_same_objects_as_the_submodules() -> None:
    assert _shared.PluginManifest is manifest.PluginManifest
    assert _shared.ContentTypeSpec is manifest.ContentTypeSpec
    assert _shared.Searchable is base.Searchable
    assert _shared.Publishable is base.Publishable
    assert _shared.WebhookReceivable is base.WebhookReceivable
    assert _shared.MetricsQueryable is base.MetricsQueryable
    assert _shared.GrowthOSPlugin is base.GrowthOSPlugin
    assert _shared.PluginQuery is base.PluginQuery
    assert _shared.PluginResult is base.PluginResult
    assert _shared.PublishResult is base.PublishResult
    assert _shared.MetricsQuerySpec is base.MetricsQuerySpec
    assert _shared.MetricsResult is base.MetricsResult
    assert _shared.CapabilityNotSupported is base.CapabilityNotSupported
    assert _shared.DomainEventPublisher is events.DomainEventPublisher
    assert _shared.RateLimiter is rate_limit.RateLimiter


def test_all_matches_actual_exported_names() -> None:
    for name in _shared.__all__:
        assert hasattr(_shared, name)
