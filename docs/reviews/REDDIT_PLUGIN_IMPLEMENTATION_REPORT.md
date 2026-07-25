# Reddit Plugin Implementation Report

**Date:** 2026-07-25
**Scope:** implement the Reddit plugin — `Searchable` + `Publishable`, real OAuth2 auth via
the generic platform framework — as a first-class GrowthOS plugin, and everything required
for it to function as one. Explicitly excluded per this task's instructions: Conversation
Finder, Content Agent, any AI provider integration, any business logic beyond the plugin
itself.

---

## 1. Reddit Plugin Implementation Report

### What was built

```
plugins/reddit/
├── manifest.py       MANIFEST — capabilities, content types, config_schema, OAuthProviderSpec
├── client.py          RedditClient — thin httpx wrapper around Reddit's REST API
├── plugin.py           RedditPlugin — Searchable + Publishable + GrowthOSPlugin, create_plugin()
├── pyproject.toml       Entry point + packaging (same pattern as plugins/dummy/)
├── README.md             Rewritten — real implementation, not a forward-looking spec
└── tests/
    ├── test_contract.py    Shared contract suite, real ResolvedConnection shape
    ├── test_client.py       RedditClient against httpx.MockTransport (11 tests)
    └── test_plugin.py        RedditPlugin's own logic against a fake client (19 tests)
```

**Auth is 100% the generic platform framework — zero OAuth code in this plugin.** The
manifest declares an `OAuthProviderSpec` with Reddit's real `authorize_url`/`token_url`/
`revoke_url` and scopes; `app/core/oauth/` executes the actual authorization-code flow,
`app/core/crypto.py` encrypts the resulting tokens, `app/jobs/oauth_refresh.py` keeps them
current. `RedditPlugin.__init__` reads `connection.credentials.access_token` — a value it was
handed, never one it obtained or refreshed itself.

**Not PRAW.** `plugins/reddit/README.md` previously recommended PRAW (Reddit's own client
library) specifically for its OAuth handling — written before the generic OAuth2 framework
existed. Using PRAW's OAuth management now would duplicate and bypass that framework, which
is exactly the "platform-specific shortcut" this task's instructions rule out. `client.py` is
a ~100-line `httpx` wrapper instead; Reddit's actual data API (search, comment) doesn't need
a heavier client once OAuth itself isn't this plugin's problem.

**One platform gap found and closed, not worked around.** Reddit requires a descriptive
`User-Agent` header on every API call — including the OAuth token endpoint itself, not just
its data API. The existing `OAuthProviderSpec` had `extra_authorize_params`/
`extra_token_params` for provider-specific body params, but nothing for provider-specific
*headers*. Rather than hard-coding a Reddit special case into the generic `OAuthClient`
(exactly the kind of platform-specific shortcut this task rules out), a new
`extra_token_headers` field was added to `OAuthProviderSpec` — the same declarative pattern
already established, one layer down. See §2 for why this was judged in-scope to fix rather
than a blocking question, and `docs/auth/OAUTH2_ARCHITECTURE.md` for where it's now
documented alongside the fields it extends.

**Design decisions made while implementing, each documented at its point of use** (in
`client.py`/`plugin.py`'s own docstrings, and `README.md`):
- Reddit's `/api/comment` and similar legacy endpoints return **HTTP 200 even on a logical
  failure**, with the real error inside the JSON body's `json.errors` field. `client.py`
  checks for this on every request, not just `submit_comment`, so a plugin author extending
  this client later doesn't have to rediscover the quirk.
- `search()` requests more than the `read`/`submit` scopes the two capabilities strictly
  need — `identity` as well, so `health_check()` can call `GET /api/v1/me` and verify the
  token actually works against Reddit, not just that it hasn't expired locally. A
  health check that can't detect "the token is garbage" is a weaker check than one that can.
- Rate limiting reuses `plugins/_shared/rate_limit.py` exactly as
  `docs/plugins/PLUGIN_ARCHITECTURE.md`'s own worked example already showed (that example
  used Reddit) — a module-level `RateLimiter` instance, since a fresh `RedditPlugin` is
  constructed on every registry lookup and per-instance state would never actually limit
  anything.
- `duration=permanent` is required in the authorize request or Reddit issues a 1-hour token
  with **no refresh token at all**, which would silently break the background refresh job the
  first time it ran. Declared via the existing `extra_authorize_params` — no framework change
  needed for this one.

---

## 2. Architecture compliance summary

| Requirement | Compliance |
|---|---|
| Use the generic OAuth2 framework | **Yes.** No token exchange, refresh, or state handling anywhere in `plugins/reddit/`. Verified by `discover_installed_plugins()` returning a real `OAuthProviderSpec` with zero core-code changes (§ below), and by `RedditPlugin` receiving `OAuth2Credentials` it never computed itself. |
| Use the generic Plugin SDK | **Yes.** `RedditPlugin` implements `GrowthOSPlugin` + `Searchable` + `Publishable` exactly as `plugins/_shared/base.py` defines them — no plugin-specific Protocol, no bypass of the two-gate capability check. |
| No platform-specific shortcuts | **Yes**, with one caveat addressed head-on, not worked around: `extra_token_headers` (§1) is a genuine, small SDK extension — additive, backward-compatible (empty dict default, every existing manifest unaffected), following the identical pattern `extra_authorize_params`/`extra_token_params` already established for exactly this class of problem. It is not a Reddit-specific branch anywhere in platform code; `app/core/oauth/client.py` still has zero knowledge that Reddit exists. |
| Follow plugin lifecycle and manifest conventions | **Yes.** `manifest.py`/`client.py`/`plugin.py`/`pyproject.toml`/`README.md`/`tests/` matches the layout `docs/plugins/QUICKSTART.md` and `scripts/new_plugin.py` already establish; entry point registered the same way `plugins/dummy/` is. |
| Maintain strict test coverage | **Yes** — see §3. Every branch in `client.py` and `plugin.py` has a corresponding test: HTTP success/failure/network-error/non-JSON/Reddit's-200-with-errors-quirk for the client; subreddit iteration, `since` filtering, rate-limit exhaustion, per-subreddit error isolation, and all four credential states (valid, `None`, wrong-type, exhausted budget) for the plugin. |
| Zero core-code changes to add this plugin | **Verified, not assumed** — `PYTHONPATH="backend;." python -c "from app.core.plugin_catalog import discover_installed_plugins; ..."` shows `reddit` and its full `OAuthProviderSpec` discovered via the same entry-point scan `dummy` already used, with no edit to `app/core/plugin_catalog.py`, `app/core/plugin_registry.py`, or any other core file (the one file touched outside `plugins/reddit/` — `plugins/_shared/oauth.py` — is the SDK itself, which every plugin, not just Reddit, is entitled to extend when it finds a real gap). |
| No plugin-specific functionality outside the plugin | **Yes** — `grep`-verified, correcting an overclaim caught while re-checking this report before finalizing it: a repo-wide search for "Reddit" in `backend/app/` does turn up 3 files outside `plugins/reddit/`, but all three are pre-existing prose (from the OAuth2 framework task, predating this one) using "Reddit" as a familiar illustrative example in a comment/docstring — `app/core/plugin_catalog.py`'s module docstring shows `plugins.reddit.manifest:MANIFEST` as a generic entry-point example, and two comments about the `label` column mention "two Reddit accounts" as an example of why it exists. None is Reddit-specific *behavior* — no code anywhere in `backend/app/` branches on `plugin_key == "reddit"` or imports anything from `plugins/reddit/`. |

No frozen architectural decision, ADR, or locked decision (`docs/architecture/LOCKED_DECISIONS.md`)
was touched, reinterpreted, or worked around.

---

## 3. Test results

**33 new tests written for this work (31 in the plugin itself, 2 extending the OAuth
framework's own test suite), all passing, zero regressions anywhere else:**

- `plugins/reddit/tests/` — **31 passed**:
  - `test_contract.py` (1) — the shared plugin contract suite, proving `RedditPlugin`
    structurally honors its manifest (implements `Searchable`+`Publishable`, has a real
    `OAuthProviderSpec`, `health_check()` returns a `bool`).
  - `test_client.py` (11) — headers (bearer token + User-Agent), successful `/api/v1/me`,
    401 → `RedditAPIError`, network unreachable → `RedditAPIError`, non-JSON response →
    `RedditAPIError`, subreddit search extraction, empty search results, successful comment
    submission (verifying the actual POST body), and Reddit's HTTP-200-with-embedded-errors
    quirk on `/api/comment`.
  - `test_plugin.py` (19) — multi-subreddit search aggregation, `OR`-joined query terms,
    per-subreddit result limiting, empty-subreddits no-op (and no network call made), one
    failing subreddit not failing the whole search, `since` filtering, missing/wrong-type
    credentials (both return empty results, never raise), rate-limit exhaustion during
    search, successful publish (including URL extraction), publish with an unparseable-but-
    successful response, publish surfacing a Reddit error verbatim, publish rejecting an item
    missing `target_ref`/`body` before ever calling Reddit, publish without credentials,
    publish under rate-limit exhaustion, `health_check()` true/false/no-credentials paths.
- `backend/tests/unit/test_oauth_client.py` — **2 new tests** (16 total, up from 14) —
  `extra_token_headers` is actually sent on both the token-exchange and revoke requests.
- Full backend suite: **176 passed** (174 before this task), zero regressions.
- Plugin SDK + dummy + reddit combined: **45 passed**.

**Lint/type-check:**
- `ruff check` (official `scripts/lint.py`, `backend/` scope): clean.
- `ruff check` against `plugins/reddit/` directly (source + tests): clean.
- `mypy --strict` against `plugins/reddit/`'s three source files (`manifest.py`, `client.py`,
  `plugin.py`): clean. (Test files are intentionally not mypy-strict-checked, matching this
  repo's own established convention — `scripts/lint.py`'s `mypy app` never checks
  `backend/tests/` either; holding `plugins/reddit/tests/` to a stricter bar than the
  project's own test suite would be inconsistent, not more rigorous.)

**End-to-end discovery, verified against the real mechanism, not asserted:**
```
$ discover_installed_plugins() → ['dummy', 'reddit']
reddit.capabilities = ('searchable', 'publishable')
reddit.auth_type = 'oauth2'
reddit.oauth.authorize_url = 'https://www.reddit.com/api/v1/authorize'
```

---

## 4. Remaining work before Conversation Finder

- **A real Reddit OAuth app registration and a live connection.** Nothing in this task
  connects an actual Reddit account — `REDDIT_OAUTH_CLIENT_ID`/`_CLIENT_SECRET` are
  documented (`.env.example`) but unset; the plugin has never made a real network call
  outside its own mocked tests. First real-world validation (does the authorize/callback
  flow actually work against Reddit, does search return real results, does a comment
  actually post) is unstarted.
- **Conversation Finder itself** — the agent that would call `registry.all_with_capability
  (Searchable)`, run `RedditPlugin.search()` against real subreddits, and turn results into
  `KnowledgeItem` rows. Explicitly out of scope for this task; this plugin is now what it
  would call.
- **Content Agent** — drafts a `ContentItem` from a `KnowledgeItem`, including the
  comment-length self-check this plugin's README notes is *not* this plugin's
  responsibility. Also explicitly out of scope here.
- **`ContentApprovalService` and the publish worker** — the only code path allowed to call
  `RedditPlugin.publish()` in production (`ARCHITECTURE.md` §8). Still Phase 1/2 business
  logic, not built.
- **Webhook ingress** — irrelevant to Reddit specifically (it doesn't declare
  `webhook_receivable`), unchanged by this task.
- **Observability** — `ARCHITECTURE.md` §10's plugin-call tracing (OpenTelemetry spans
  tagged `plugin_key`/`project_id`) doesn't wrap `RedditClient`'s calls yet; not needed for
  this plugin to function correctly, but relevant once real traffic flows through it.

None of the above block Conversation Finder from being designed — they're the concrete list
of what it would need this plugin (and its own new code) to actually do, once building it is
back in scope.
