# Plugin: Twitter/X

**Capabilities:** `Searchable`, `Publishable`
**Auth:** OAuth2 + PKCE (required) — see `docs/auth/OAUTH2_ARCHITECTURE.md`.
**Status:** Implemented — see `docs/reviews/TWITTER_LINKEDIN_IMPLEMENTATION_REPORT.md`. Not
yet connected to a real account or consumed by any agent.

## Purpose

Search recent tweets and post approved tweets/replies via X API v2.

## Architecture — uses the generic OAuth2 framework, not any X SDK

Like `plugins/reddit/`, this plugin implements no OAuth logic itself. `manifest.py` declares
an `OAuthProviderSpec`; `app/core/oauth/` executes the authorize/exchange/refresh/revoke
flow generically. `client.py` is a small `httpx` wrapper that only ever consumes an
already-valid access token handed to it via `ResolvedConnection.credentials` — it never
requests, refreshes, or stores a token.

X API v2's OAuth2 Authorization Code flow **requires PKCE unconditionally**, for both
confidential and public clients. This is why PKCE (RFC 7636) was built into the platform's
OAuth2 framework from day one (`app/core/oauth/pkce.py`) — this plugin is what the framework
was originally designed to support, and it needed zero framework changes: `manifest.py`
simply declares `pkce="required"` and the platform does the rest.

## Auth setup

Register an app in the [X Developer Portal](https://developer.x.com/) with OAuth 2.0 enabled
(confidential client — GrowthOS holds a client secret). Redirect URI:
`{OAUTH_CALLBACK_BASE_URL}/api/v1/oauth/twitter/callback`. Set `TWITTER_OAUTH_CLIENT_ID` /
`TWITTER_OAUTH_CLIENT_SECRET` — see `.env.example`.

Requested scopes: `tweet.read`, `tweet.write`, `users.read`, `offline.access`.
`offline.access` is required to receive a `refresh_token` at all — without it X issues a
2-hour access token with no way to refresh it, which would silently break the platform's
background refresh job (`app/jobs/oauth_refresh.py`), the same failure mode Reddit's
`duration=permanent` param guards against.

## Config schema (`TwitterConnectionConfig`)

X's recent-search endpoint has no per-connection scoping equivalent to Reddit's subreddit
allowlist — it searches all public posts by default, filtered only by `PluginQuery.terms` at
call time. What is connection-level is how noisy that search is allowed to be:

- `exclude_retweets: bool = True`
- `exclude_replies: bool = False`
- `lang: str | None = None` — ISO 639-1 code, e.g. `"en"`

## `search()`

Builds one query string (`terms` OR-joined, wrapped in parens if there's more than one, plus
the config filters above) and makes a single `GET /2/tweets/search/recent` call — unlike
Reddit's per-subreddit loop, there's no natural per-connection fan-out to make here.
`max_results` is clamped to X's required 10–100 range regardless of `PluginQuery.limit`; a
`limit` below 10 still only returns up to `limit` results after local filtering (`since`, then
truncation), since X won't return fewer than 10 by request.

## `publish()`

Posts a tweet via `POST /2/tweets`. `ContentItem.target_ref`, if present, is passed as
`reply.in_reply_to_tweet_id` — a reply; otherwise a standalone tweet.

## Rate limits

X API rate limits are tier-dependent (Free/Basic/Pro) and comparatively low on the
Free/Basic tiers. The shared rate limiter here is configured at 60 requests/15 minutes,
matching Basic tier's recent-search limit — the tightest of the endpoints this plugin calls,
so treat it as the binding constraint in the system until/unless the project upgrades tier.
Document the actual tier this project is registered under once connected, since it
materially changes what `search()` can cover (full-archive vs. recent-only search).

## Known constraints

- Free-tier search access is limited to recent tweets only (X API v2's "recent search"
  endpoint covers roughly the last 7 days); if `conversation_finder`'s `search_terms` need
  historical coverage, that's a paid-tier requirement, not something this plugin can work
  around.
- `content_types` declares a 280-character limit (the standard, non-Premium per-tweet limit).
  GrowthOS does not assume a Premium/X Blue account with the higher 25,000-character limit —
  if the connected account has one, this manifest constant would need updating, not worked
  around at the plugin-call-site level.
- `search_recent`'s response embeds authors under `includes.users`, not inline per-tweet —
  `client.py` returns the raw response body rather than a flattened list so `plugin.py` can
  join the two, unlike Reddit where each post is already self-contained.
