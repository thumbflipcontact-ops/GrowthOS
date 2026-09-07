# Plugin: Reddit

**Capabilities:** `Searchable`, `Publishable`
**Auth:** `oauth2` (scopes: `read`, `submit`, `identity`) — required only for `publish()`;
`search()` is unauthenticated. See "Public sitewide search" below.
**Status:** implemented and live — both Conversation Finder and Content Agent already consume
this plugin end-to-end (`agents/conversation_finder/agent.py`'s `Searchable` fan-out,
`agents/content_agent/agent.py`'s `_SUPPORTED_PLATFORMS`/`prompts/reddit_reply.py`).

## Purpose

Discover relevant Reddit posts sitewide, with no connected account required; post approved
replies once a project does connect one. Reddit was chosen as the first plugin implemented —
see `docs/decisions/0005-first-plugin-reddit.md` for why.

## Auth

Uses the platform's generic OAuth2 framework (`docs/auth/OAUTH2_ARCHITECTURE.md`,
`app/core/oauth/`) — this plugin contains **no OAuth code**. Its manifest
(`plugins/reddit/manifest.py`) declares an `OAuthProviderSpec` with Reddit's real endpoints;
the platform executes the authorization-code flow, stores the resulting tokens
envelope-encrypted (ADR 0010), and refreshes them automatically
(`app/jobs/oauth_refresh.py`). This plugin's `create_plugin()` receives an already-valid
`OAuth2Credentials.access_token` and does nothing else with the token lifecycle.

**Not PRAW.** An earlier version of this document recommended PRAW (Reddit's own client
library) specifically because it manages OAuth token refresh — written before the generic
OAuth2 framework existed. Using PRAW's own OAuth handling now would duplicate (and bypass)
that framework, which is exactly the kind of plugin-specific shortcut the platform exists to
prevent. `plugins/reddit/client.py` is a small, dependency-light `httpx` wrapper instead —
Reddit's actual data API (search, comment) is simple enough that PRAW's main value (OAuth
lifecycle management) is no longer needed here.

**Provider-specific quirks**, declared in the manifest, not hand-coded in platform logic (see
`plugins/_shared/oauth.py`'s `OAuthProviderSpec`):
- `extra_authorize_params={"duration": "permanent"}` — without this, Reddit issues a 1-hour
  access token with **no refresh token at all**, which would silently break the background
  refresh job the first time it ran.
- `extra_token_headers={"User-Agent": ...}` — Reddit requires a descriptive `User-Agent` on
  every API call, including the OAuth token endpoint itself. `extra_token_headers` didn't
  exist on `OAuthProviderSpec` before this plugin was implemented — it was added because
  Reddit needed it; see `docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md`.
- `pkce="unsupported"` — Reddit's OAuth2 implementation does not support RFC 7636.

Connect a Reddit account via the standard plugin-connection flow
(`docs/plugins/QUICKSTART.md` §8): set `REDDIT_OAUTH_CLIENT_ID`/`REDDIT_OAUTH_CLIENT_SECRET`
(from Reddit's own app-registration page), then
`POST /api/v1/projects/{project_id}/plugin-connections/reddit/oauth/start`.

## Configuration (`config_schema`)

```python
class RedditConnectionConfig(BaseModel):
    subreddits: list[str] = []
```

Which subreddits this connection searches — e.g. ScoutSEO might set `["SEO", "juststart",
"bigseo", "TechSEO"]`. An empty list is valid (a connection can exist, fully authorized,
before anyone has picked subreddits); `search()` simply returns nothing until it's set.

## `search()` — public sitewide search

Calls `GET /search.rss` on `www.reddit.com` — Reddit's public, unauthenticated search
endpoint, sitewide (not restricted to any subreddit), joining `PluginQuery.terms` with `OR`.
**RSS, not JSON** — `GET /search.json` was tried first and confirmed via direct production
testing to return HTTP 403 with a bot-detection HTML challenge page from Railway's datacenter
IP range; `/search.rss` returns a normal 200 with real Atom XML from the same IP. This matches
MentionCatch's own stated architecture ("reads Reddit's public RSS feeds and search results").
`client.py`'s `_parse_search_rss()` maps Atom `<entry>` elements back to the same dict shape
the JSON endpoint would have produced (`name`/`title`/`permalink`/`selftext`/`author`/
`subreddit`/`created_utc`), so `plugin.py`'s `_to_plugin_result()`/`_created_at()` needed no
changes — `score`/`num_comments` don't exist in RSS and are simply omitted, since nothing
downstream reads them. **No OAuth token or connected account is required** — this is
deliberate: a project gets Reddit lead discovery from the moment it's created (see
`backend/app/api/v1/projects.py::create_project()`, which auto-creates a `CONNECTED`,
credential-less `PluginConnection` for every new project), with connecting an account only
ever needed to actually reply (see `publish()` below). Results are filtered by
`PluginQuery.since` if given and capped at `PluginQuery.limit`.

**A Reddit-side failure (403/429/network error) is deliberately NOT swallowed into `[]`** —
it propagates out of `search()`, unlike every other plugin's convention. This is a direct
fix for the actual production incident that exposed the RSS-vs-JSON issue above in the first
place: `search()` originally caught `RedditAPIError` and returned `[]`, which made a real
Reddit-side failure indistinguishable from "genuinely no matching posts" — the dashboard
showed "0 raw results" with no way to tell which had happened, twice (first the JSON
endpoint's 403s, then a 429 from a too-generous rate budget). `agents/conversation_finder/
agent.py`'s own per-plugin `try/except` is what actually guarantees one plugin's failure
can't fail the whole discovery run — that safety net already existed one layer up, so this
plugin swallowing its own errors was redundant *and* was hiding real signal. The only thing
that still returns `[]` silently is our *own* deliberate self-throttle (see below) — nothing
went wrong there, we just chose not to call Reddit that cycle.

`RedditConnectionConfig.subreddits` and `RedditClient.search_subreddit()` (the original,
OAuth-authenticated, per-subreddit search) still exist but are **not called by `search()`
today** — kept, not deleted, as a dormant capability a future "narrow to my favorite
subreddits" power-user feature could reuse.

**Rate limiting for the public endpoint** is deliberately much more conservative than the
OAuth rate limiter below (see `plugin.py`'s `_PUBLIC_RATE_LIMITER`), and is a single bucket
shared across every project (`_PUBLIC_BUCKET_KEY`) rather than one per project — this hits
Reddit from one shared outbound IP regardless of which project's search triggered it. The
budget was originally set to 10/min on the (wrong) assumption Reddit's own limit was roughly
that generous — direct production testing showed Reddit can 429 a *second* request within
about a second of the first from the same IP, so the budget was cut to 3/min; this number is
still a guess, not a confirmed safe ceiling, and may need to go lower still if 429s keep
showing up in real run errors (see above — they're visible now, so this is actually
observable going forward). Reddit's terms treat any commercial/monetized use of its API as
requiring a negotiated agreement (no self-serve pricing exists for this); this endpoint is
used deliberately conservatively and in good faith while that's evaluated further, not as a
settled-safe approach — see the platform's own outreach to Reddit's developer platform team.

## `publish()`

Posts a comment reply to the thread/comment referenced by `ContentItem.target_ref` (a Reddit
"fullname", e.g. `t3_abc123`). Only ever called by the publish worker on an `approved`
item — see `docs/plugins/PLUGIN_ARCHITECTURE.md`. Reddit's `/api/comment` endpoint returns
HTTP 200 even on a logical failure (rate limit, banned, deleted thread) — `client.py` checks
the response body's `json.errors` field and raises regardless of status code, so a failure is
never mistaken for success.

## Rate limits

Two independent limiters, both via the shared token-bucket helper
(`plugins/_shared/rate_limit.py`), each one shared instance per process (a fresh `RedditPlugin`
is constructed on every registry lookup, so per-instance state would never actually limit
anything):
- `_RATE_LIMITER` (60/min) — Reddit's documented OAuth-client rate limit, gating `publish()`
  and `health_check()`. A throttled `publish()` call returns
  `PublishResult(success=False, error="Rate limited...")`.
- `_PUBLIC_RATE_LIMITER` (3/min, shared across every project) — a deliberately conservative
  budget for the public, unauthenticated `search()` endpoint (see above). Our own
  self-throttle still returns `[]` quietly when this budget is exhausted; an actual
  rate-limit response *from Reddit* (a 429 that got through the budget anyway, or any other
  Reddit-side failure) raises instead — see above.

## Known constraints

- Reddit's spam filters can shadow-affect new/low-karma accounts — `publish()` surfaces the
  API response verbatim in `PublishResult.error` so a failed post is visible, not silently
  swallowed.
- Comment length limit (10,000 chars, declared as `content_types[0].max_length` in the
  manifest) is not enforced by this plugin itself — that's the drafting agent's
  self-check responsibility (Content Agent, not yet built) before an item ever reaches
  `pending_review`.
- `health_check()` calls `GET /api/v1/me`, which requires the `identity` scope — one more
  than the `read`/`submit` this plugin's capabilities strictly need, added specifically so
  health checks verify the token actually works against Reddit, not just that it hasn't
  expired locally.

## Testing

```bash
uv pip install -e plugins/reddit --python backend/.venv   # from the repo root
backend/.venv/Scripts/python -m pytest plugins/reddit/tests -p no:cov   # Windows
backend/.venv/bin/python -m pytest plugins/reddit/tests -p no:cov       # macOS/Linux
```

Three layers, all against mocks — no test ever makes a real call to Reddit:
- `tests/test_contract.py` — the shared plugin contract suite
  (`plugins/_shared/tests/test_plugin_contract.py`), proving this plugin structurally honors
  its manifest.
- `tests/test_client.py` — `RedditClient` against `httpx.MockTransport`, including Reddit's
  HTTP-200-with-embedded-errors quirk.
- `tests/test_plugin.py` — `RedditPlugin`'s own logic (subreddit iteration, `since`
  filtering, rate limiting, per-subreddit error isolation, missing-credentials handling)
  against a fake `RedditClient` double.
