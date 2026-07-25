# Plugin: Google Analytics

**Capabilities:** `MetricsQueryable` only
**Version 2:** implements `MetricsQueryable` instead of being forced through `Searchable` —
see `docs/decisions/0007-plugin-discovery-and-interface-segmentation.md`. Under the original
design this plugin's `search()` had to awkwardly map a parameterized metrics query onto a
free-text `PluginQuery`/`PluginResult` shape built for discussion search; that mapping is
gone because the interface now fits what this plugin actually does.

## Purpose

Signal source, not an engagement channel — traffic, conversion, and behavior data that
future `analytics_agent` (Phase 3) and, more immediately, `customer_finder` (to identify
high-intent existing visitors) can read.

## Auth

OAuth2 (Google Analytics Data API, GA4), tokens stored encrypted, read-only scope
(`analytics.readonly`).

## `query_metrics()`

Wraps GA4's reporting API directly:

```python
async def query_metrics(self, spec: MetricsQuerySpec) -> MetricsResult:
    # spec.metric_keys e.g. ["sessions", "conversions"], spec.dimensions e.g. ["source"],
    # spec.date_range — maps directly onto GA4's runReport request shape, no translation
    # through a search-shaped intermediate.
    ...
```

## Manifest

```python
MANIFEST = PluginManifest(
    key="google_analytics",
    interface_version="1.0",
    capabilities=["metrics_queryable"],
    content_types=[],           # nothing publishable
    config_schema=GAConnectionConfig,   # GA4 property ID, OAuth scopes
    auth_type="oauth2",
)
```

## Why no `Publishable`

There is nothing to publish to Google Analytics — this plugin's manifest simply omits
`publishable` from `capabilities`, and the registry's structural Protocol check means any
code attempting to request `Publishable` for this plugin fails at the type-check/registry
level (`docs/plugins/PLUGIN_ARCHITECTURE.md`), not by hitting an unimplemented method at
runtime.
