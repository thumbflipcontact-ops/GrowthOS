# Plugin: Twitter/X

**Capabilities:** `Searchable`, `Publishable`

## Purpose

Search relevant tweets/threads and post approved replies or original tweets.

## Auth

OAuth2 (X API v2), tokens stored encrypted. Tier (Free/Basic/Pro) determines search
coverage and rate limits — document the actual tier this project uses here once connected,
since it materially changes what `search()` can cover (full-archive vs. recent-only search).

## `publish()`

Posts a tweet or reply per `ContentItem.target_ref` (tweet ID being replied to, if any).

## Rate limits

X API rate limits are tier-dependent and comparatively low on free/basic tiers — the shared
rate limiter's config for this plugin should be treated as the tightest constraint in the
system until/unless the project upgrades tier.

## Known constraints

Free-tier search access is limited to recent tweets only; if `conversation_finder`'s
`search_terms` need historical coverage, that's a paid-tier requirement, not something this
plugin can work around.
