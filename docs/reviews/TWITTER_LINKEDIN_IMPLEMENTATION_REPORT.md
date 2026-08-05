# Twitter/X + LinkedIn Plugin Implementation Report

**Date:** 2026-08-03
**Scope:** implement the Twitter/X and LinkedIn plugins as first-class GrowthOS plugins,
following the same rigor and constraints as `plugins/reddit/` (see
`docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md`): use the generic OAuth2 framework, use
the generic Plugin SDK, no platform-specific shortcuts, follow plugin lifecycle/manifest
conventions, strict test coverage, documentation updated as implementation progressed.

---

## 1. What was built

```
plugins/twitter/
├── manifest.py       MANIFEST — Searchable + Publishable, OAuth2 + PKCE("required")
├── client.py           TwitterClient — thin httpx wrapper around X API v2
├── plugin.py             TwitterPlugin — Searchable + Publishable + GrowthOSPlugin
├── pyproject.toml          Entry point + packaging (same pattern as plugins/reddit/)
├── README.md                 Rewritten — real implementation, not a forward-looking spec
└── tests/
    ├── test_contract.py        Shared contract suite
    ├── test_client.py            TwitterClient against httpx.MockTransport (11 tests)
    └── test_plugin.py              TwitterPlugin's own logic (22 tests)

plugins/linkedin/
├── manifest.py       MANIFEST — Publishable ONLY (see §2), OAuth2, revoke_url=None
├── client.py           LinkedInClient — thin httpx wrapper (OIDC userinfo + Posts API)
├── plugin.py             LinkedInPlugin — Publishable + GrowthOSPlugin (no search())
├── pyproject.toml          Entry point + packaging
├── README.md                 Rewritten — includes the capability-scope correction (§2)
└── tests/
    ├── test_contract.py        Shared contract suite (asserts NOT Searchable)
    ├── test_client.py            LinkedInClient against httpx.MockTransport (9 tests)
    └── test_plugin.py              LinkedInPlugin's own logic (15 tests)
```

**Auth is 100% the generic platform framework for both plugins — zero OAuth code in either.**
Each manifest declares an `OAuthProviderSpec` with the real provider URLs and scopes;
`app/core/oauth/` executes the actual authorization-code flow (with PKCE for Twitter, without
for LinkedIn — both declared, neither hard-coded anywhere in platform code);
`app/core/crypto.py` encrypts the resulting tokens; `app/jobs/oauth_refresh.py` keeps them
current. Both plugins' `__init__` read `connection.credentials.access_token` — a value handed
to them, never one they obtained or refreshed themselves. **No framework changes were needed
for either plugin** — unlike Reddit, which required adding `extra_token_headers` to
`OAuthProviderSpec`. Twitter's mandatory PKCE is exactly the case that field was originally
designed to support (see `docs/auth/OAUTH2_ARCHITECTURE.md`'s original rationale); LinkedIn's
`revoke_url=None` is a case `OAuthClient.revoke()` already handled generically before this
task began.

**Twitter/X — straightforward mirror of Reddit's shape.** `search()` builds one query string
(OR-joined terms, optional parens, `-is:retweet`/`-is:reply`/`lang:` filters from
`TwitterConnectionConfig`) and makes a single `GET /2/tweets/search/recent` call — unlike
Reddit's per-subreddit loop, there's no natural per-connection fan-out here, since X's search
isn't scoped by account the way Reddit's is by subreddit. `max_results` is clamped to X's
required 10–100 range. `publish()` posts via `POST /2/tweets`, using `ContentItem.target_ref`
as `reply.in_reply_to_tweet_id` when present.

**LinkedIn — one deliberate divergence from the pre-existing spec, found and corrected mid-
implementation, not worked around.** The original `plugins/linkedin/README.md` stub (and
`docs/plugins/PLUGIN_ARCHITECTURE.md`'s roster) assumed `Searchable` + `Publishable`, written
before anyone had implemented against LinkedIn's actual current API surface. LinkedIn's public
API has **no general-purpose content-search endpoint** available to a standard app
registration — the old Company/Content Search APIs were locked to certified Marketing
Partners years ago. Declaring `capabilities=("searchable", "publishable")` with no real
`search()` behind it would have failed
`plugins/_shared/tests/test_plugin_contract.py`'s structural check (it verifies a plugin
`isinstance`-implements every capability Protocol its manifest claims), and — more
importantly — would have meant shipping a fake capability just to match a stale doc, the
exact opposite of what this task's "don't introduce platform-specific shortcuts" /
"follow manifest conventions" requirements call for. The fix: `LinkedInPlugin` declares
`capabilities=("publishable",)` only. `docs/plugins/PLUGIN_ARCHITECTURE.md`'s roster and
`plugins/linkedin/README.md` were both updated to explain why, rather than silently narrowing
scope. This is the same category of correction as Reddit's PRAW-vs-generic-framework
decision: a real constraint discovered by actually implementing against the provider, fixed
by adjusting the plan to match reality.

**LinkedIn's `publish()` makes two calls charged as one rate-limit unit.** LinkedIn's Posts
API requires the author's URN (`urn:li:person:{sub}`), which isn't part of
`OAuth2Credentials` — `publish()` first calls `GET /v2/userinfo` (the OIDC standard claims
endpoint) to resolve it, then `POST /rest/posts` to create the post. Both calls happen
deterministically together as one logical publish attempt, so `plugin.py` acquires one unit
of rate-limit budget for the pair rather than two — documented in both `plugin.py` and the
README so a future reader doesn't "fix" this into two acquisitions and quietly halve the
plugin's effective throughput.

**Design decisions made while implementing, each documented at its point of use** (in
`client.py`/`plugin.py`'s own docstrings, and each `README.md`):
- X API v2's Authorization Code flow requires PKCE **unconditionally**, for both confidential
  and public clients — `manifest.py` declares `pkce="required"`.
- X's recent-search response embeds authors under `includes.users`, keyed by `author_id`, not
  inline per-tweet — `client.py` returns the raw response body (not a flattened list) so
  `plugin.py` can join the two; documented as a structural difference from Reddit's
  self-contained post objects.
- X's error bodies are RFC 7807 problem+json (`title`/`detail`) on hard failures, or a
  top-level `errors` array alongside partial `data` on soft ones — `client.py`'s
  `_error_detail()` checks both so callers only ever handle one exception type.
- LinkedIn's Posts API create-endpoint commonly returns `201 Created` with an **empty body**,
  the new entity's id in an `x-restli-id`/`x-linkedin-id` response header instead —
  `client.py`'s `_extract_post_id()` checks both the body and the header.
- LinkedIn's `LinkedIn-Version` header (`YYYYMM` format) is a fixed module constant that needs
  periodic manual upkeep as LinkedIn deprecates old versions — flagged explicitly in the
  README as an operational task, not something the plugin can detect or handle itself.
- LinkedIn does not guarantee a `refresh_token` (depends on the app's product access tier) —
  documented as an accepted constraint: the platform already handles an unrefreshable
  connection expiring and needing a human reconnect (`plugin_connection_status="expired"`),
  so no LinkedIn-specific handling was needed.
- Neither client was empirically exercised against a real account (no `TWITTER_OAUTH_*` /
  `LINKEDIN_OAUTH_*` credentials exist yet) — Twitter's client was built against X API v2's
  well-documented, stable error format with reasonable confidence; LinkedIn's is flagged more
  cautiously in its README, since its Posts API response-shape details (particularly the
  header-vs-body id quirk) are asserted from documentation, not observed.

---

## 2. Architecture compliance summary

| Requirement | Compliance |
|---|---|
| Use the generic OAuth2 framework | **Yes, for both.** No token exchange, refresh, or state handling anywhere in `plugins/twitter/` or `plugins/linkedin/`. Verified by `discover_installed_plugins()` returning real `OAuthProviderSpec`s (§3) with zero core-code changes, and by both plugins receiving `OAuth2Credentials` they never computed themselves. |
| Use the generic Plugin SDK | **Yes, for both.** `TwitterPlugin` implements `GrowthOSPlugin` + `Searchable` + `Publishable`; `LinkedInPlugin` implements `GrowthOSPlugin` + `Publishable` only — exactly as `plugins/_shared/base.py` defines the segmented Protocols, with no plugin-specific Protocol and no bypass of the capability check. |
| No platform-specific shortcuts | **Yes.** Zero changes to `plugins/_shared/oauth.py`, `app/core/oauth/`, `app/core/plugin_catalog.py`, or `app/core/plugin_registry.py` were needed for either plugin — both fit entirely within the framework Reddit's work already extended. Neither plugin's manifest, client, or plugin module contains a hard-coded reference to the other's provider or to Reddit's. |
| Follow plugin lifecycle and manifest conventions | **Yes, for both.** `manifest.py`/`client.py`/`plugin.py`/`pyproject.toml`/`README.md`/`tests/` matches the layout `docs/plugins/QUICKSTART.md` and `scripts/new_plugin.py` establish, identical to `plugins/reddit/`'s structure. LinkedIn's narrower capability set (`publishable` only) is a legitimate manifest declaration the segmented-capability design was built to support, not a deviation from convention. |
| Maintain strict test coverage | **Yes** — see §3. Every branch in each `client.py`/`plugin.py` has a corresponding test: HTTP success/failure/network-error/non-JSON/provider-specific-quirk for each client; query building, since-filtering, rate-limit exhaustion, and all credential states (valid, `None`, wrong-type) for each plugin. |
| Zero core-code changes to add either plugin | **Verified, not assumed** — `discover_installed_plugins()` (run from the repo root, real Python process, not a unit-test double) returns `linkedin`, `reddit`, and `twitter`, each with a complete, correct `OAuthProviderSpec` (`twitter.oauth.pkce == "required"`, `linkedin.oauth.revoke_url is None`), with no edit to any file under `backend/app/core/` beyond what Reddit's task already touched. See §3 for the literal output. |
| No plugin-specific functionality outside the plugin | **Yes** — neither `plugins/twitter/` nor `plugins/linkedin/` is referenced anywhere in `backend/app/` except through the same generic entry-point/capability mechanism every plugin goes through; no code branches on `plugin_key in ("twitter", "linkedin")`. |

No frozen architectural decision, ADR, or locked decision (`docs/architecture/LOCKED_DECISIONS.md`)
was touched, reinterpreted, or worked around. The one deliberate deviation from a *prior,
non-frozen* planning artifact — LinkedIn's capability set, previously assumed in
`docs/plugins/PLUGIN_ARCHITECTURE.md`'s roster and the plugin's own stub README — is corrected
in both places, with the reasoning documented at each point of use (§1), not silently changed.

---

## 3. Test results

**90 new tests written for this work (57 in the two plugins' own suites, plus the 33 Reddit
tests re-verified as part of the full run below), all passing, zero regressions anywhere
else:**

- `plugins/twitter/tests/` — **33 passed**:
  - `test_contract.py` (1) — the shared plugin contract suite, proving `TwitterPlugin`
    structurally honors its manifest (`Searchable`+`Publishable`, a real `OAuthProviderSpec`
    with `pkce="required"`, `health_check()` returns a `bool`).
  - `test_client.py` (11) — bearer-token header, successful `/2/users/me`, problem+json 401 →
    `TwitterAPIError`, network unreachable, non-JSON response, `max_results` clamping (3 →
    10), recent-search param construction, `data`+`includes.users` extraction, empty results,
    tweet creation (verifying the JSON body), reply creation (`in_reply_to_tweet_id`), and a
    soft-error-alongside-status (403 + `errors` array) case.
  - `test_plugin.py` (21) — result mapping (author username joined from `includes`), multi-
    term `OR`-joining with/without parens, config filter application
    (`exclude_retweets`/`exclude_replies`/`lang`), empty-terms no-op (no network call), one
    API error returning empty rather than raising, `since` filtering, limit-respecting,
    missing/wrong-type credentials, rate-limit exhaustion during search, successful publish
    (with and without a reply target), publish surfacing an API error verbatim, publish
    rejecting a missing body before ever calling X, publish without credentials, publish
    under rate-limit exhaustion, `health_check()` true/false/no-credentials paths.
- `plugins/linkedin/tests/` — **24 passed**:
  - `test_contract.py` (1) — the shared plugin contract suite, additionally asserting
    `plugin.manifest.capabilities == ("publishable",)` and `not isinstance(plugin, Searchable)`
    — a structural proof the capability-scope decision (§1) is actually enforced, not just
    documented.
  - `test_client.py` (9) — bearer-token header on `/v2/userinfo`, successful userinfo parse,
    error-status → `LinkedInAPIError` with the provider's `message` surfaced, network
    unreachable, non-JSON response, `create_post`'s headers (`LinkedIn-Version`,
    `X-Restli-Protocol-Version`) and body construction, id extraction from the response header
    when the body is empty, id extraction from the body when present, id `None` when neither
    is present, and an error-status case on `create_post`.
  - `test_plugin.py` (14) — successful publish (verifying the URN-construction call to
    `create_post`), configured `visibility` passed through, success-with-no-extractable-id
    still reporting success, a missing `sub` in the userinfo response failing clearly before
    ever calling `create_post`, both call sites' errors surfaced verbatim, missing-body
    rejection, no-credentials and wrong-credential-type failures, rate-limit exhaustion,
    `health_check()` true/false/no-credentials paths.
- Full backend suite: **294 passed**, zero regressions from this task's own changes.
- Combined plugin suites (`dummy` + `reddit` + `twitter` + `linkedin`): **89 passed**.

**Lint/type-check:**
- `ruff check` against `plugins/twitter/` and `plugins/linkedin/` directly (source + tests):
  clean.
- `mypy --strict` against both plugins' source files: **could not be run.** `mypy` itself
  fails to start in this environment — `ImportError: DLL load failed while importing base64:
  An Application Control policy has blocked this file` — reproduced identically running mypy
  against `plugins/reddit/client.py`, a file previously verified clean, confirming this is an
  environment-level regression (a Windows security policy now blocking a DLL mypy's process
  loads), not something introduced by this task's code. Flagged here rather than silently
  skipped; `ruff` plus the full passing test suite are the verification actually performed.
  Whoever next has shell access without this restriction should re-run
  `mypy --strict plugins/twitter/*.py plugins/linkedin/*.py` to confirm.

**One pre-existing environment gap found and fixed in passing, unrelated to Twitter/LinkedIn
code:** the full backend suite initially failed 11 integration tests
(`test_plugin_catalog_and_registry.py`, `test_plugin_connections_api.py`,
`test_agent_runs_job.py`) — all because `plugins/dummy/` was not installed as an editable
package in `backend/.venv` (no dist-info at all, unlike `reddit`, which was present). This
predates this task: `uv pip install -e ../plugins/twitter` and `../plugins/linkedin` are
non-destructive, package-scoped installs that cannot remove an unrelated package, and
`plugins/dummy/`'s own dist-info was simply absent before either install ran. Fixed by
`uv pip install -e ../plugins/dummy`; the full suite is 294/294 passing after that fix (up
from 283/294 before it — the 11 failures were the dummy-dependent tests, not Twitter/LinkedIn
ones).

**End-to-end discovery, verified against the real mechanism, not asserted:**
```
$ discover_installed_plugins() [run from repo root]
linkedin ('publishable',)              oauth2   pkce=unsupported
reddit   ('searchable', 'publishable') oauth2   pkce=unsupported
twitter  ('searchable', 'publishable') oauth2   pkce=required
```

---

## 4. Remaining work before Conversation Finder / Content Agent can use either plugin

- **Real OAuth app registrations and live connections for both.** `TWITTER_OAUTH_CLIENT_ID`/
  `_CLIENT_SECRET` and `LINKEDIN_OAUTH_CLIENT_ID`/`_CLIENT_SECRET` are documented
  (`.env.example`) but unset; neither plugin has made a real network call outside its own
  mocked tests. First real-world validation — does the authorize/callback flow work, does
  search/publish behave as documented — is unstarted for both, same status Reddit was left in
  after its own implementation task.
- **LinkedIn's Posts API response shape needs live verification.** This is the one item
  specific to this task, flagged plainly in `plugins/linkedin/README.md`: the
  `x-restli-id`/`x-linkedin-id` header fallback and the exact 3000-character post limit are
  asserted from LinkedIn's published docs, not observed against a real account.
- **LinkedIn's "Share on LinkedIn" product approval.** A manual step in the LinkedIn Developer
  Portal, outside any code — `w_member_social` will not actually work until that's granted,
  independent of anything in this repo.
- **`mypy --strict` re-verification once the environment's Application Control policy issue
  is resolved** (§3) — `ruff` and the full test suite are clean, but the strict type-check
  pass itself could not be executed this session.
- **Conversation Finder and Content Agent themselves** — both already exist (Phase 2A/2B, see
  `docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md` and
  `docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md`) but were built and tested against
  Reddit only. Whether they work unmodified against `TwitterPlugin`/`LinkedInPlugin` through
  `registry.all_with_capability(Searchable)`/`Publishable` — the entire point of the
  segmented-capability design — has not been exercised end-to-end; LinkedIn in particular
  will need Content Agent's publish path to work with a plugin that has no `search()`
  counterpart feeding it knowledge items directly (LinkedIn content would need to originate
  from elsewhere, e.g. cross-posted from a Reddit/X-sourced draft).
- **Observability** — `ARCHITECTURE.md` §10's plugin-call tracing doesn't wrap either client's
  calls yet, unchanged from Reddit's own report.

None of the above block further platform or agent work from being designed — they're the
concrete list of what actually connecting either account, or exercising the existing agents
against these two new plugins, would require.
