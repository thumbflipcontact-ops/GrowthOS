# Plugin: Search Console

**Capabilities:** `MetricsQueryable` only
**Version 2:** implements `MetricsQueryable` instead of being forced through `Searchable` —
see `docs/decisions/0007-plugin-discovery-and-interface-segmentation.md`.

## Purpose

Read-only signal source — indexing status, search performance, and coverage data for a
project's own site. This is the core data source ScoutSEO itself is built around, and within
GrowthOS it's primarily consumed by `customer_finder` and (Phase 3) `analytics_agent` for
GrowthOS's own operational insight, not by content/outreach agents.

## Auth

OAuth2 (Search Console API), tokens stored encrypted, read-only scope
(`webmasters.readonly`).

## `query_metrics()`

Wraps the Search Console API's query methods (performance data, URL inspection, sitemaps)
directly onto `MetricsQuerySpec`/`MetricsResult` — no intermediate free-text search mapping,
same reasoning as `google_analytics`.

## Manifest

```python
MANIFEST = PluginManifest(
    key="search_console",
    interface_version="1.0",
    capabilities=["metrics_queryable"],
    content_types=[],
    config_schema=SearchConsoleConnectionConfig,   # verified site URL, OAuth scopes
    auth_type="oauth2",
)
```

## Why no `Publishable`

Same reasoning as `google_analytics` — nothing to publish to; `publishable` is deliberately
absent from `capabilities`.
