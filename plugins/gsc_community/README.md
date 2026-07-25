# Plugin: Google Search Console Community

**Capabilities:** `Searchable`, `Publishable`

## Purpose

Google's official product forum for Search Console. Directly relevant to ScoutSEO's ICP
(founders/marketers debugging GSC issues) — likely the single highest-signal source for
Phase 1, and a strong candidate for the first plugin actually implemented.

## Auth

The forum runs on Google Groups infrastructure without a first-class public API; this
plugin will likely need a scoped scraping/read approach (with explicit rate limiting and
respect for robots.txt / terms of service) for `search()`, and an authenticated browser
session or forum account for `publish()`. Document the concrete implementation approach
here once built — this is the plugin most likely to need a design decision the other,
API-backed plugins don't.

## `search()`

Searches recent threads for configured terms (e.g. "coverage report errors", "sitemap not
indexed").

## `publish()`

Posts a reply to a specific thread.

## Known constraints

No official rate-limit documentation exists for this surface — start conservative (a few
requests per minute) and make the limit configurable per `plugin_connections` row rather
than hardcoded, so it can be tuned without a code change if the actual tolerance turns out
to be different.
