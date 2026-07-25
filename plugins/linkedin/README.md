# Plugin: LinkedIn

**Capabilities:** `Searchable`, `Publishable`

## Purpose

Search posts/comments for relevant discussion (where LinkedIn's API allows), and send
approved connection messages / post approved content on the founder's behalf.

## Auth

OAuth2 via LinkedIn's Marketing/Community Management API. Note: LinkedIn's public API
surface for search is much more restricted than Reddit's — this plugin's `search()` is
expected to lean more heavily on content the founder's own account has visibility into
(feed, groups) than open discovery. Document actual coverage here once implemented against
real API access, since LinkedIn's available scopes change based on partnership tier.

## `publish()`

Sends a connection request/message or publishes a post, per `ContentItem.type`
(`linkedin_message`). Only called on `approved` items.

## Rate limits

LinkedIn enforces strict per-endpoint daily caps, generally stricter than Reddit's. The
shared rate limiter should be configured conservatively and `content_agent`'s
`max_drafts_per_run` tuned so approvals don't queue up faster than they can actually be
published in a day.

## Known constraints

LinkedIn actively penalizes automation-pattern behavior on the account holder's side —
this is precisely the risk the human-approval gate exists to manage; this plugin should
never gain a "batch send" capability that bypasses per-item review.
