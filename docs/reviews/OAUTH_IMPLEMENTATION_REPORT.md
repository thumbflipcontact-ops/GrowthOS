# OAuth Implementation Report

**Date:** 2026-07-25
**Scope:** implement the generic OAuth2 platform framework exactly as specified in
`docs/auth/OAUTH2_ARCHITECTURE.md` (ADR 0011, now Accepted). Explicitly excluded per this
task's instructions: the Reddit plugin, any other plugin, and any business logic — this is
the platform mechanism only, with zero real OAuth-capable plugin built against it yet.

---

## 1. What was built

| Design doc section | What exists now |
|---|---|
| §1 Architecture | `app/core/oauth/{pkce,state,client,errors}.py` — a generic, provider-agnostic OAuth2 client. `app/core/crypto.py` — the envelope-encryption primitive ADR 0010 specified but nothing had implemented yet (see §3, deviation 1). |
| §2 Database changes | Two migrations: `plugin_connection_status` gains `expired`; `plugin_connections` gains `label`, `token_expires_at`, `granted_scopes`, a new unique constraint, and the refresh-sweep partial index. `database/schema.sql`, `docs/database/SCHEMA.md`, `docs/database/ERD.md` all updated to match. |
| §3 Platform APIs | `POST .../plugin-connections/{plugin_key}/oauth/start`, `GET /api/v1/oauth/{plugin_key}/callback` (global, not project-scoped), `POST .../plugin-connections/{connection_id}/oauth/disconnect` — all three exactly as specified, including the callback's redirect-based (not raw-JSON) outcome reporting. |
| §4 Plugin SDK additions | `plugins/_shared/oauth.py` (`OAuthProviderSpec`), `plugins/_shared/credentials.py` (`OAuth2Credentials`, `ApiKeyCredentials`), `ResolvedConnection` in `base.py`, `PluginManifest.oauth` field, discovery-time + contract-suite validation that an `oauth2` manifest declares a real spec. |
| §5 Flow diagrams | All four flows (connect, background refresh, reconnect, disconnect) implemented as designed — see `app/services/oauth_connection.py` and `app/core/oauth/refresh.py`. |
| §6 Security considerations | Signed stateless CSRF state (`app/core/oauth/state.py`), session-binding check (state's `user_id` must match the current session), PKCE support (`app/core/oauth/pkce.py`, opt-in per provider), redaction (`access_token`/`refresh_token`/`client_secret` added to `app/core/logging.py`'s redaction set), best-effort revoke, refresh-race handling via `FOR UPDATE SKIP LOCKED`. |
| §7 Migration impact | Both migrations applied and verified against a real (embedded) Postgres. `create_plugin()`'s signature changed to `ResolvedConnection` — `plugins/dummy/`, `scripts/new_plugin.py`'s templates, and the shared contract suite all updated together. |
| §8 Implementation plan | Steps 1–10 all complete, in the specified order (each step's own tests passed before starting the next). Step 11 (Reddit) explicitly not started, per this task's scope. |

**Verification:** `python scripts/lint.py` (ruff + mypy --strict) — clean. Full backend test
suite: **174 passed** (132 before this task; 77 OAuth-framework-specific tests across 9 new
test files, 6 more in `test_config.py`, 2 more in the plugin-contract suite, and 4 in a new
`test_logging_redaction.py` — see §2, deviation 10). Plugin SDK suite
(`plugins/_shared/tests`, `plugins/dummy/tests`): **14 passed**, unaffected. Zero regressions
anywhere in the pre-existing suite.

---

## 2. Deviations from the approved design

None change what the design specified structurally — all are implementation-level decisions
the design doc didn't (and reasonably couldn't) spell out to the byte, or small corrections
found while actually exercising the flow end-to-end.

1. **Envelope encryption itself had to be built** (`app/core/crypto.py`, AES-256-GCM via the
   `cryptography` package — new dependency, `cryptography>=43,<44`). ADR 0010 and
   `plugin_connections.credentials_encrypted`/`credential_data_key_wrapped` existed since
   Phase 1, but nothing had ever implemented the actual encrypt/decrypt primitive — OAuth is
   its first real consumer. The design doc referenced ADR 0010's *pattern* throughout without
   flagging that the primitive itself didn't exist yet; building it was a prerequisite, not
   an optional extra.
2. **Master key derivation**: `Settings.credential_master_key` (an arbitrary-length operator
   string) is reduced to exactly 32 bytes via `SHA-256(secret)` (`derive_master_key`). The
   design doc didn't specify this mechanically; SHA-256 reduction is the standard, simplest
   correct choice and requires no change to how operators set the env var.
3. **`label` generalized beyond OAuth.** The design doc scoped `label` primarily to the OAuth
   connection flow, but it's a `plugin_connections` schema column — `PluginConnectionService`
   (the pre-existing, non-OAuth connection-creation path from the Platform Improvement pass)
   and its repository query needed the same `label` awareness, or the column would be
   inconsistently honored depending on which path created a connection. Fixed so both paths
   agree.
4. **`OAuthStartRequest` needs a route-level default** (`= OAuthStartRequest()`) for
   `POST .../oauth/start` to accept a body-less request — discovered via integration testing.
   FastAPI treats a Pydantic-model body parameter as required unless the *route signature*
   gives it a default, even when every field on the model itself has one. Fixed at the route,
   not by forcing every caller to send `{}`.
5. **Callback error reporting is two-tier, not one.** The design said outcomes "redirect...
   never a raw JSON error body" — implemented as: a session that fails GrowthOS's own
   authentication dependency (no cookie, expired session) still gets the standard JSON 401
   every other authenticated endpoint in this API returns (that's a different failure class —
   never having reached the OAuth flow at all); a session that *is* authenticated but whose
   OAuth-specific state fails verification, or whose token exchange fails, redirects with an
   `?error=...` param as designed. This reads as the more correct interpretation of "outcomes
   of the OAuth flow" than a blanket catch over the auth dependency too, but is worth flagging
   as a judgment call.
6. **`PluginRegistry`'s constructor now requires `settings`** (to derive the master key when
   resolving credentials) — implied by the design ("the registry decrypts...") but not stated
   as an explicit signature change. Zero production call sites existed yet (only tests), so
   this was free.
7. **No true concurrent-transaction test for `FOR UPDATE SKIP LOCKED`.** The refresh sweep's
   row-locking is implemented exactly as designed, but `tests/integration/test_oauth_refresh.py`
   cannot exercise genuine two-transaction lock contention — this repo's test harness gives
   each test one transaction/savepoint (see `conftest.py`), and simulating real concurrent
   locking needs a second, independent database connection outside that savepoint, which
   doesn't exist as test infrastructure yet. What *is* tested: every refresh outcome (success,
   permanent failure, transient failure, missing refresh token, multiple due connections in
   one sweep) against a single session. This is a known, explicitly-flagged gap, not a silent
   one — building a second-connection test harness is a reasonable follow-up if the concurrency
   path is ever suspected of a real bug.
8. **No operational master-key-rotation job/script.** `app/core/crypto.py` implements the
   primitive `docs/security/SECURITY.md`'s rotation runbook needs (`rewrap_data_key`), and it's
   unit-tested (round-trips correctly, old key can no longer decrypt after rewrap) — but a
   script/job that walks every `plugin_connections` row and actually performs a rotation isn't
   built. Judged as ops tooling outside "the generic OAuth framework," the same way the
   original design doc itself left the master key's storage location (local secret vs. KMS)
   unresolved.
9. **`session_credentials` auth type still has no defined credential shape.** The design
   doc's Plugin SDK additions (§4) only defined `OAuth2Credentials` and `ApiKeyCredentials` —
   `PluginRegistry._resolve_credentials` returns `None` for `session_credentials`, consistent
   with the design's own scope, not a new gap introduced here.
10. **Caught during the final verification pass, not the first draft:** §6 said
    `access_token`/`refresh_token`/`client_secret` would be added to
    `app/core/logging.py`'s `_REDACTED_KEYS`. Writing this report's first draft claimed that
    was already done; re-checking the actual file before finalizing found it wasn't — fixed
    on the spot (`app/core/logging.py`, plus a new `test_logging_redaction.py`, since no test
    covered `_redact_secrets` at all before this, for any key). Noted here deliberately: this
    report's own claims were re-verified against the actual code, not assumed correct because
    they were intended.

---

## 3. Test coverage summary

77 new tests specifically exercise the OAuth framework, across:

- `test_crypto.py` (8) — envelope encrypt/decrypt round-trip, wrong-key/tampered-ciphertext
  failure, rotation (`rewrap_data_key`).
- `test_oauth_pkce.py` (7) — verifier length/charset, challenge determinism, an RFC 7636
  Appendix B known-answer test.
- `test_oauth_state.py` (8) — round-trip (with and without a PKCE verifier), wrong secret,
  tampered token, expiry, garbage input.
- `test_oauth_client.py` (16) — authorize-URL construction (including PKCE and
  provider-specific extra params), successful/failing code exchange, `client_secret_basic`
  vs `client_secret_post`, network-error handling, `invalid_grant` → `PermanentRefreshFailure`
  vs. any other failure → base `TokenExchangeFailed`, revoke (including the no-`revoke_url`
  no-op case) — all against `httpx.MockTransport`, never real network.
- `test_plugin_catalog_oauth_validation.py` (3) — discovery rejects an `oauth2` manifest
  missing `oauth`, accepts one with a valid spec, unaffected non-`oauth2` manifests still
  discovered.
- `test_plugin_registry_credential_resolution.py` (5) — the registry actually decrypts and
  hands a plugin real `OAuth2Credentials`/`ApiKeyCredentials`, returns `None` when nothing's
  stored yet, fails loudly (`InvalidTag`) on a wrong master key.
- `test_oauth_connection_service.py` (15) — `start()` (authorize URL, unknown/non-OAuth
  plugin rejection), `handle_callback()` (create, reconnect-updates-same-row, audit logging,
  invalid/mismatched state, deleted project, exchange failure, multiple labels), `disconnect()`
  (clears credentials, best-effort revoke including provider-unreachable, audit logging,
  never calls revoke with no stored credentials).
- `test_oauth_api.py` (9) — full HTTP-level connect flow, tampered-state redirect,
  unauthenticated-callback 401, reconnect via the API, disconnect via the API (including
  cross-project rejection), multiple labels via the API.
- `test_oauth_refresh.py` (9) — refreshes a due connection, ignores a far-future one, ignores
  a disconnected one, permanent failure → `expired` + audit log, transient failure → stays
  `connected`, missing refresh token → `expired` with zero network calls, refresh-token
  preservation when a provider omits rotation, multiple due connections in one sweep,
  `REFRESH_WINDOW` sanity check against the job's cron cadence.

Plus 6 new tests in `test_config.py` (`oauth_client_credentials` — found/missing/half-set,
hyphenated plugin keys, default URLs), 2 new tests in the shared plugin contract suite (an
`oauth2` manifest missing/having a spec), and 4 in `test_logging_redaction.py` (verifying
`_redact_secrets` actually redacts `access_token`/`refresh_token`/`client_secret`,
case-insensitively, leaves unrelated fields alone, and still redacts the pre-existing keys —
no test covered this function at all before this task).

---

## 4. Remaining items, intentionally deferred

- **The Reddit plugin itself** — explicitly out of scope for this task, as instructed. The
  framework is designed so implementing it should now be almost entirely PRAW integration and
  `search()`/`publish()` logic, with near-zero OAuth-specific code — that claim is untested
  until Reddit is actually built.
- **The webhook ingress route** (`POST /webhooks/{plugin_key}`) — unrelated to OAuth
  specifically; still Phase 2+, unchanged by this work.
- **`api_key`/`session_credentials` credential-setting flows** — no request path writes
  `credentials_encrypted` for these auth types; only `oauth2` (this task) has a real flow.
- **Master-key rotation tooling** — the primitive exists and is tested; the operational
  script/job that would actually run a rotation in production doesn't (see deviation 8).
- **Genuine concurrent-transaction test coverage for the refresh sweep's row locking** — see
  deviation 7.

---

## 5. Final assessment

The generic OAuth2 framework is built, tested, and matches the approved design in every
structural respect — every deviation above is an implementation-level decision the design
doc left open (by nature of being a design doc, not a spec to the byte) or a correction found
by actually exercising the flow end-to-end, never a departure from what was approved. ADR
0011 is Accepted and the index updated. The platform is ready for the next real decision
point: building the Reddit plugin against this framework, which was always gated on this work
existing first.
