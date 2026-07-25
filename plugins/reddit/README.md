# Plugin: Reddit

**Capabilities:** `Searchable`, `Publishable`
**Auth:** `oauth2` (scopes: `read`, `submit`, `identity`)
**Status:** implemented — see `docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md`. Not yet
connected to a real Reddit account, and not yet consumed by any agent (Conversation Finder /
Content Agent are explicitly out of scope until after this plugin — see `ROADMAP.md`).

## Purpose

Search subreddits for relevant discussions; post approved replies. Reddit was chosen as the
first plugin implemented — see `docs/decisions/0005-first-plugin-reddit.md` for why.

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

## `search()`

For each configured subreddit, calls `GET /r/{subreddit}/search` (restricted to that
subreddit, sorted newest-first), joining `PluginQuery.terms` with `OR`. Results are
deduplicated per subreddit call (not across subreddits), filtered by `PluginQuery.since` if
given, and capped at `PluginQuery.limit` across all subreddits combined. One subreddit's
search failing does not fail the whole call — see `plugin.py`'s per-subreddit
`try/except RedditAPIError`.

## `publish()`

Posts a comment reply to the thread/comment referenced by `ContentItem.target_ref` (a Reddit
"fullname", e.g. `t3_abc123`). Only ever called by the publish worker on an `approved`
item — see `docs/plugins/PLUGIN_ARCHITECTURE.md`. Reddit's `/api/comment` endpoint returns
HTTP 200 even on a logical failure (rate limit, banned, deleted thread) — `client.py` checks
the response body's `json.errors` field and raises regardless of status code, so a failure is
never mistaken for success.

## Rate limits

Reddit API: ~60 requests/minute per OAuth client. Enforced via the shared token-bucket helper
(`plugins/_shared/rate_limit.py`), one shared limiter instance per process (see `plugin.py`'s
module-level `_RATE_LIMITER` — a fresh `RedditPlugin` is constructed on every registry
lookup, so per-instance state would never actually limit anything). A throttled `search()`
call returns whatever results it already gathered rather than raising; a throttled
`publish()` call returns `PublishResult(success=False, error="Rate limited...")`.

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
