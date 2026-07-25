# Plugin: Reddit

**Capabilities:** `Searchable`, `Publishable`
**Status:** first plugin to be implemented — see `docs/decisions/0005-first-plugin-reddit.md`
and `ROADMAP.md` Phase 1.

## Purpose

Search subreddits for relevant discussions; post approved replies. This is the plugin the
entire Phase 1 trust-model proof runs on — the concrete target for "a real thread gets
discovered, a reply gets drafted, you approve it, it posts for real"
(`ROADMAP.md` Phase 1 exit criterion).

## Auth

OAuth2 (Reddit script/web app), refresh token stored encrypted in
`plugin_connections.credentials_encrypted`. Requires `read` and `submit` scopes. Recommended
client library: **PRAW** (Python Reddit API Wrapper) — mature, handles OAuth token refresh
and rate-limit backoff, avoids hand-rolling HTTP calls against Reddit's API for the first
plugin implementation.

## `search()`

Wraps Reddit's search API, scoped to a configurable subreddit list (from the project's
plugin config, not this plugin's code — e.g. ScoutSEO might watch `r/SEO`, `r/juststart`,
`r/bigseo`, `r/TechSEO`).

## `publish()`

Posts a comment reply to the thread referenced by `ContentItem.target_ref` (a Reddit thing
ID). Only ever called by the publish worker on an `approved` item — see
`docs/plugins/PLUGIN_ARCHITECTURE.md`.

## Rate limits

Reddit API: ~60 requests/minute per OAuth client. Enforced via the shared token-bucket
helper, keyed per project (each project's Reddit connection should use its own app
credentials to avoid one project's activity throttling another's).

## Known constraints

- Reddit's spam filters can shadow-affect new/low-karma accounts — `publish()` surfaces the
  API response verbatim in `PublishResult.error` so a failed post is visible, not silently
  swallowed.
- Comment length limit (10,000 chars) enforced by `content_agent`'s self-check before an
  item ever reaches `pending_review`.
