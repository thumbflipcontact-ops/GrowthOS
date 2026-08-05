# Plugin: LinkedIn

**Capabilities:** `Publishable` (not `Searchable` — see "Why no `search()`" below)
**Auth:** OAuth2 — see `docs/auth/OAUTH2_ARCHITECTURE.md`.
**Status:** Implemented — see `docs/reviews/TWITTER_LINKEDIN_IMPLEMENTATION_REPORT.md`. Not
yet connected to a real account, not yet exercised against a live LinkedIn app, and not yet
consumed by any agent.

## Purpose

Publish approved posts to LinkedIn on the founder's behalf.

## Why no `search()`

The original plugin scaffold (and `docs/plugins/PLUGIN_ARCHITECTURE.md`'s roster) assumed
`Searchable` + `Publishable`, mirroring Reddit and Twitter. Implementing against LinkedIn's
actual current API surface, that assumption doesn't hold: LinkedIn has no general-purpose
content-search endpoint available to a standard app registration. The old Company/Content
Search APIs that once allowed this were locked down to certified Marketing Partners years
ago and are not part of the self-serve developer program this plugin can register under.

Declaring `capabilities=("searchable", "publishable")` with no real `search()` behind it
would fail `plugins/_shared/tests/test_plugin_contract.py`'s structural check, and more
importantly would violate the same principle Reddit's implementation was held to: don't
declare a capability you haven't implemented and tested. So this manifest declares
`publishable` only. If `conversation_finder` needs LinkedIn discussion coverage later, that
would require either LinkedIn's restricted Marketing Partner search products (a business/
partnership decision, not an engineering one) or a different discovery mechanism entirely —
out of scope for this plugin. This mirrors the earlier Reddit-vs-PRAW self-correction: found
mid-implementation, fixed by adjusting the manifest to match reality rather than building a
fake capability to match a stale doc.

## Architecture — uses the generic OAuth2 framework, not any LinkedIn SDK

Like `plugins/reddit/` and `plugins/twitter/`, this plugin implements no OAuth logic itself.
`manifest.py` declares an `OAuthProviderSpec`; `app/core/oauth/` executes the authorize/
exchange/refresh/revoke flow generically. `client.py` is a small `httpx` wrapper that only
ever consumes an already-valid access token handed to it via `ResolvedConnection.credentials`
— it never requests, refreshes, or stores a token.

LinkedIn declares no public token-revocation endpoint for third-party apps (unlike Reddit/X),
so `manifest.py` sets `oauth.revoke_url=None` — a case the platform's `OAuthClient.revoke()`
already handles generically (it returns immediately without an HTTP call; local
disconnection still proceeds regardless, per `docs/auth/OAUTH2_ARCHITECTURE.md` §6). No
framework change was needed for this.

## Auth setup

Register an app in the [LinkedIn Developer Portal](https://www.linkedin.com/developers/) and
request the **"Share on LinkedIn"** product — this is a manual approval step in LinkedIn's
portal, outside this plugin's code, and is required before `w_member_social` will actually
work. Redirect URI: `{OAUTH_CALLBACK_BASE_URL}/api/v1/oauth/linkedin/callback`. Set
`LINKEDIN_OAUTH_CLIENT_ID` / `LINKEDIN_OAUTH_CLIENT_SECRET` — see `.env.example`.

Requested scopes: `openid`, `profile` (OpenID Connect — back the `GET /v2/userinfo` call
`health_check()` and `publish()` both use to resolve the member's numeric id into the URN
LinkedIn's Posts API requires), and `w_member_social` (the posting permission itself).

## Config schema (`LinkedInConnectionConfig`)

- `visibility: Literal["PUBLIC", "CONNECTIONS"] = "PUBLIC"` — passed straight through to
  LinkedIn's Posts API `visibility` field.

There's no Reddit-style scoping config here since this plugin has no `search()` to scope.

## `publish()`

Two LinkedIn calls, always made together as one logical operation:

1. `GET /v2/userinfo` to resolve the member's `sub` claim into `urn:li:person:{sub}` (the
   `author` LinkedIn's Posts API requires — there is no way to post without it, and it isn't
   information the platform's `OAuth2Credentials` already carries).
2. `POST /rest/posts` with that URN, the item's `body` as `commentary`, and the connection's
   configured `visibility`.

Both calls are charged against a single unit of this plugin's rate-limit budget (see "Rate
limits" below) rather than two, since they're never meaningfully separable — one publish
attempt is one logical operation regardless of how many LinkedIn requests it costs.

## Rate limits

LinkedIn does not publish a simple, fixed per-app rate limit the way Reddit and X do —
documented limits vary by API product and access tier, and this plugin has not yet been
approved for a real tier. The shared rate limiter here is a deliberately conservative
placeholder (25 calls/day) pending real numbers once this plugin is actually connected;
tune it down further, not up, if actual limits turn out tighter. `content_agent`'s
`max_drafts_per_run` should stay tuned so approvals don't queue up faster than they can
actually be published in a day — the same caution the original plugin stub called out.

## Known constraints

- **Not empirically verified against a real LinkedIn account.** Unlike Reddit (built and
  tested against Reddit's actual documented HTTP-200-with-embedded-errors quirk) and Twitter
  (built against X API v2's documented problem+json error format), this client is built
  against LinkedIn's published API documentation only — this plugin has never made a real
  call to LinkedIn. The specific field names/shapes in `client.py` (particularly
  `create_post`'s `x-restli-id`/`x-linkedin-id` header fallback and the exact 3000-character
  post limit) should be treated as best-effort until verified against a connected account.
- `LinkedIn-Version` (`client.py`'s `_LINKEDIN_API_VERSION`) is a fixed `YYYYMM` string
  LinkedIn's Posts API requires on every call, valid for a rolling window before LinkedIn
  deprecates it. This needs periodic manual upkeep (bump the string, redeploy) — an
  operational task for whoever runs this in production, not something the plugin can detect
  or handle itself.
- LinkedIn actively penalizes automation-pattern behavior on the account holder's side —
  this is precisely the risk the human-approval gate exists to manage; this plugin should
  never gain a "batch send" capability that bypasses per-item review.
- A refresh token is not guaranteed. LinkedIn issues access tokens valid for roughly 60 days;
  whether a `refresh_token` is included depends on the app's product access. If none is
  returned, the connection simply expires when the access token does and needs a human
  reconnect (`plugin_connection_status="expired"`) — the same path the platform already
  handles for a permanent refresh failure, so no special-casing was needed here either.
