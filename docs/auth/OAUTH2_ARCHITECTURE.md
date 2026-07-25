# OAuth2 Plugin Framework — Design

**Status: Approved (ADR 0011 Accepted, 2026-07-25) and implemented** — see
`docs/reviews/OAUTH_IMPLEMENTATION_REPORT.md` for what was actually built, including any
deviations from this design.

**Why this exists:** `docs/auth/AUTHENTICATION.md` has always said "Plugin OAuth flows...
use the standard OAuth2 authorization-code flow" in one sentence, with zero mechanism behind
it. The Platform Readiness Review flagged this as the actual blocker for Reddit (and every
other OAuth-capable plugin). This document is that mechanism, designed once, generically,
before Reddit — not designed *as* Reddit and generalized later.

**Scope discipline:** this document changes nothing about the four capability Protocols
(`Searchable`/`Publishable`/`WebhookReceivable`/`MetricsQueryable`, ADR 0007), nothing about
manifest-based discovery (ADR 0007), nothing about the envelope-encryption *pattern* (ADR
0010) — it extends the plugin manifest with OAuth-specific metadata and adds a new platform
subsystem that uses the existing encryption pattern, the existing background-job
infrastructure (Arq, ADR 0002), and the existing signed-token pattern
(`app/core/security.py`). No new category of infrastructure is introduced.

**Four judgment calls made in this design that you may want to weigh in on** (each explained
where it appears below, flagged again here for visibility):

1. **Multiple connections per plugin per project** via a new `label` column, rather than
   staying at one connection per (project, plugin) — see §2.
2. **A new `expired` connection status**, distinct from the existing `error`, so the API/UI
   can tell "will retry automatically" apart from "needs a human to re-authorize" — see §2.
3. **OAuth state is stateless** (a signed, time-limited token embedding everything needed),
   not a server-side table — see §3, §6.
4. **`create_plugin()`'s signature changes** to receive a typed `ResolvedConnection` instead
   of the raw `PluginConnection` ORM row, so plugins never see encrypted bytes or the
   database model directly — see §4, §7.

---

## 1. OAuth2 Architecture Design

### The core principle

**A plugin declares; the platform executes.** This is the same pattern already locked in for
everything else a plugin exposes (config schema → generic connection form, ADR 0009;
capabilities → generic registry dispatch, ADR 0007). OAuth is not a new pattern — it's this
pattern applied to one more thing a plugin needs to describe instead of implement.

A plugin's manifest gains one new field, populated only when `auth_type="oauth2"`:

```
MANIFEST = PluginManifest(
    key="reddit",
    ...
    auth_type="oauth2",
    oauth=OAuthProviderSpec(
        authorize_url="https://www.reddit.com/api/v1/authorize",
        token_url="https://www.reddit.com/api/v1/access_token",
        revoke_url="https://www.reddit.com/api/v1/revoke_token",
        scopes=("read", "submit"),
        pkce="unsupported",   # Reddit's OAuth2 doesn't support PKCE as of this writing
        token_endpoint_auth_method="client_secret_basic",
    ),
)
```

That's the entire plugin-side surface. No plugin ever constructs an authorize URL, exchanges
a code, refreshes a token, or touches `client_id`/`client_secret`. All of that lives in a new
platform subsystem, `backend/app/core/oauth/`:

```
backend/app/core/oauth/
├── pkce.py       code_verifier / code_challenge generation (RFC 7636)
├── state.py      signed, time-limited OAuth state token (mirrors app/core/security.py's
│                   session-token pattern — same itsdangerous mechanism, different payload)
├── client.py      OAuthClient — generic authorize-URL builder, code↔token exchange,
│                   refresh, revoke; the ONLY code in the system that makes HTTP calls to
│                   an authorize_url/token_url/revoke_url
└── errors.py      OAuthError hierarchy (invalid_grant, provider_unreachable, ...) mapped
                    onto app/core/errors.py's existing domain exceptions
```

`OAuthClient` is provider-agnostic: it takes an `OAuthProviderSpec` plus operator-configured
`client_id`/`client_secret` as arguments and executes the RFC 6749 authorization-code flow
(with optional PKCE, RFC 7636) against whatever URLs and scopes the spec declares. Nothing in
`client.py` knows Reddit exists. Every provider in your list — Google (Search Console,
Analytics), LinkedIn, X, GitHub, Slack, Discord, Notion, HubSpot, Stripe Connect — implements
the same RFC; provider differences are entirely data (`OAuthProviderSpec`'s fields), which is
exactly why this is designed as a manifest extension and not a per-plugin code path.

### Why not push OAuth logic into each plugin?

Because that's the V1 mistake the design review already caught once, in a different guise:
`ARCHITECTURE.md` §1's "if you find yourself writing `if project.slug == "scoutseo"`, the
abstraction is wrong" generalizes directly to "if you find yourself writing an HTTP client
for a token endpoint inside a plugin, the abstraction is wrong." Every plugin's OAuth dance is
RFC 6749 with different URLs and scopes — implementing it 12 times (or 100+ times, at this
system's stated target) means 12 subtly different bugs in token refresh, expiry handling, and
CSRF protection instead of one, reviewed, tested implementation.

### Where credential resolution happens

Today, `PluginRegistry._load_plugin_instance()` passes the raw `PluginConnection` ORM row
(carrying `credentials_encrypted` as opaque bytes) into `create_plugin()`. This forced
`plugins/_shared/base.py`'s `Publishable.publish(item: object)` pattern — untyped, because the
real type lives in `backend/app`, which plugins can't import. OAuth makes this worse: a
plugin would need to unwrap the envelope-encrypted JSON blob itself to get an access token,
which means every OAuth plugin re-implementing decryption, or `plugins/_shared` importing
`backend/app`'s encryption code — both wrong, for the reasons `ARCHITECTURE.md` §5's trust
model section already establishes.

The fix: the registry decrypts (already the documented boundary — "decryption happens only
inside plugin instance construction," `docs/security/SECURITY.md`) and hands the plugin a
typed, already-decrypted `ResolvedConnection` (§4) instead of the raw ORM row. This is a
small, mechanical generalization of something the registry already does implicitly — it just
makes the boundary a real type instead of an implicit convention.

---

## 2. Required database changes

All changes are additive to `plugin_connections`; no existing table is redesigned, no ADR is
reversed.

```sql
-- New value on an existing enum — additive, does not invalidate existing rows.
alter type plugin_connection_status add value 'expired';

alter table plugin_connections
    add column label            text not null default 'default',
    add column token_expires_at timestamptz,
    add column granted_scopes   text[] not null default '{}';

alter table plugin_connections
    drop constraint plugin_connections_project_id_plugin_key_key,
    add constraint plugin_connections_project_id_plugin_key_label_key
        unique (project_id, plugin_key, label);

-- Hot-path index for the token-refresh sweep (§7) — same partial-index pattern already
-- used for domain_events' undispatched-rows query.
create index idx_plugin_connections_oauth_refresh
    on plugin_connections (token_expires_at)
    where token_expires_at is not null and status = 'connected';
```

**`label` (judgment call #1).** Requirement: "support multiple connections per organization
where appropriate." An org already gets this for free across projects (each project has its
own `plugin_connections` rows). Within a *single* project, today's schema hard-caps one
connection per plugin (`unique(project_id, plugin_key)`) — which blocks a real case for
several of the providers on your list (a project running two Reddit accounts for different
subreddit strategies; a project with two Slack workspaces). `label` (default `"default"`,
so every existing/typical connection is unaffected) turns that cap into a per-plugin choice
made at connection-creation time, not a schema limitation. Nothing about capability
enablement, config validation, or the two-gate mechanism changes — `label` just
disambiguates *which* connection to a given plugin a request means.

**`token_expires_at` and `granted_scopes` are plaintext, deliberately.** Neither is a
credential. Expiry needs to be queryable by the refresh sweep (§7) without decrypting
anything; granted scopes need to be readable by the connection-status API without decrypting
anything either (a user should be able to see what they authorized without an encrypt/decrypt
round trip). The actual `access_token`/`refresh_token` continue to live exclusively inside
`credentials_encrypted`, envelope-encrypted exactly as ADR 0010 already specifies — this
design adds no new encryption primitive, no new key material, no new column carrying secret
material. It's the same `credentials_encrypted` / `credential_data_key_wrapped` pair,
storing a JSON payload (`{"access_token": ..., "refresh_token": ..., "token_type": ...}`)
instead of whatever opaque shape a non-OAuth `auth_type` stores there today.

**`expired` status (judgment call #2).** `plugin_connection_status` today is `connected` /
`error` / `disconnected`. A refresh failure is not one thing: a transient failure (network
blip, provider 5xx) should leave the connection `connected` — it'll be retried next sweep,
and a user shouldn't be alarmed by it. A **permanent** failure (`invalid_grant` — the refresh
token itself was revoked, expired, or the user revoked access on the provider's side) means
no amount of retrying helps; a human must re-authorize. Collapsing both into `error` would
either alarm users over transient blips or hide connections that genuinely need
re-authorization behind a status that also means "will fix itself." `expired` exists so
"needs reconnect" is a distinct, queryable, UI-actionable state — a partial index or a filter
on `status = 'expired'` is how a future "reconnect these" UI panel gets built, instead of
guessing from `error`'s free-form nature.

**No new table.** OAuth client `client_id`/`client_secret` per provider are **not**
per-connection secrets — they're operator-level app-registration secrets, one per plugin,
shared across every project's connections to that plugin (the same trust tier as
`SECRET_KEY`/`CREDENTIAL_MASTER_KEY` already in `.env` — see §6, §7). They live in
configuration, not the database. OAuth state (§3) is stateless by design, so there is no
`oauth_states` table either.

---

## 3. Platform APIs

Two constraints shape every endpoint below:

- **The redirect URI registered with each provider must be a single fixed URL** — most
  providers (Reddit, GitHub, Slack, ...) require an exact registered redirect URI, not a
  wildcard/templated one. This means the callback endpoint **cannot** be
  project-scoped in its path (`/projects/{project_id}/.../callback` would need a different
  registered URI per project, which providers don't support). Identity (which project, which
  plugin, which label, which user) has to travel inside the `state` parameter instead — this
  is the reason for the signed-state design in §6, not an incidental choice.
- **The authorize-initiation endpoint, by contrast, is GrowthOS's own API** — the frontend
  calls it before ever redirecting the browser to the provider, so it can be normally
  project-scoped like every other route.

```
POST /api/v1/projects/{project_id}/plugin-connections/{plugin_key}/oauth/start
     body: {"label": "default"}                          (optional, defaults "default")
     → 200 {"authorize_url": "https://www.reddit.com/api/v1/authorize?..."}

     Requires require_project_access, same as every other project-scoped route. Builds a
     signed state token embedding {project_id, plugin_key, label, user_id, code_verifier
     (if PKCE), nonce, issued_at}, builds the authorize_url from the plugin's
     OAuthProviderSpec + this deployment's configured client_id + the fixed callback URL,
     and returns it as JSON — the frontend navigates the browser there itself (SPA-friendly:
     lets the frontend show a loading state / handle a build failure before navigating away).
     If a connection with this (project_id, plugin_key, label) already exists in
     `expired`/`error` status, this is also how reconnect (§5) is initiated — same endpoint,
     no separate "reconnect" route needed, since starting the flow again for an existing
     label is indistinguishable from starting it for a new one until the callback resolves.

GET  /api/v1/oauth/{plugin_key}/callback?code=...&state=...
     → 302 redirect to a fixed, configured frontend URL (success or failure state
       communicated via query param, never via an attacker-influenceable "return_to")

     NOT project-scoped in the path — see above. Requires an authenticated GrowthOS session
     (the browser round-trips through the provider and back, carrying the same-site session
     cookie the whole way) AND a valid signed state whose embedded user_id matches the
     current session's user. Verifies state (signature + max-age, exactly like
     verify_session_token), exchanges the code via OAuthClient, envelope-encrypts the
     resulting tokens, upserts the plugin_connections row (creates it if this is a first
     connect, updates it in place if this is a reconnect — same row, same id, same `config`/
     `capabilities_enabled` survive a reconnect), writes an audit_log row
     (`plugin_connection.oauth_connected` or `.oauth_reconnected`).

POST /api/v1/projects/{project_id}/plugin-connections/{connection_id}/oauth/disconnect
     → 204

     Requires require_project_access. Best-effort calls the plugin's revoke_url if declared
     (failure to reach the provider does not block disconnection — see §6); clears
     credentials_encrypted/credential_data_key_wrapped/token_expires_at/granted_scopes on the
     row rather than deleting it (config and capabilities_enabled are preserved so
     reconnecting doesn't require re-entering plugin-specific config); sets
     status='disconnected'; writes an audit_log row.
```

No refresh endpoint exists — refresh is exclusively a background job (§7), never a
user/API-triggered synchronous action, so no route calls into the provider's token endpoint
on a user's request path.

`GET /api/v1/projects/{project_id}/plugin-connections` (already built, Platform Improvement
pass) needs no shape change — `PluginConnectionResponse` gains `label`, `token_expires_at`
(so a frontend can show "expires in 3 days" / "reconnect needed"), and `granted_scopes`, all
additive fields.

---

## 4. Plugin SDK additions

Everything below lives in `plugins/_shared/` and stays dependency-free (stdlib + pydantic
only, matching the existing SDK).

```python
# plugins/_shared/oauth.py
from typing import Literal

PKCEPolicy = Literal["required", "supported", "unsupported"]

@dataclass(frozen=True, slots=True)
class OAuthProviderSpec:
    authorize_url: str
    token_url: str
    revoke_url: str | None = None
    scopes: tuple[str, ...] = ()
    pkce: PKCEPolicy = "unsupported"
    token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = (
        "client_secret_basic"
    )
    extra_authorize_params: dict[str, str] = field(default_factory=dict)
    extra_token_params: dict[str, str] = field(default_factory=dict)
    extra_token_headers: dict[str, str] = field(default_factory=dict)
```

`extra_authorize_params`/`extra_token_params` exist because real providers deviate from bare
RFC 6749 in small, provider-specific ways — Google requires `access_type=offline&prompt=
consent` on the authorize call to get a refresh token at all; HubSpot and Notion have their
own quirks. Rather than the platform special-casing providers, plugins declare whatever extra
key-value pairs their provider's docs require, and `OAuthClient` merges them in generically.
This is what keeps the platform provider-agnostic even as it accumulates 12+ real providers.

`extra_token_headers` was added implementing the Reddit plugin (not present in the original
design this document proposed) — Reddit requires a descriptive `User-Agent` header on every
API call, including the token endpoint itself, and the original `OAuthProviderSpec` had no
way to declare a provider-required *header* (only body params). Same pattern, one layer
down: declared per-provider, merged in generically by `OAuthClient`, never special-cased. See
`docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md`.

```python
# plugins/_shared/manifest.py — one new optional field, default None
@dataclass(frozen=True, slots=True)
class PluginManifest:
    ...
    oauth: OAuthProviderSpec | None = None   # required in practice when auth_type="oauth2";
                                              # not enforced at the dataclass level (see below)
```

```python
# plugins/_shared/credentials.py
@dataclass(frozen=True, slots=True)
class OAuth2Credentials:
    access_token: str
    refresh_token: str | None
    token_type: str
    expires_at: datetime
    granted_scopes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ApiKeyCredentials:
    api_key: str

Credentials = OAuth2Credentials | ApiKeyCredentials | None
```

```python
# plugins/_shared/base.py — the connection object create_plugin() receives changes shape
@dataclass(frozen=True, slots=True)
class ResolvedConnection:
    project_id: uuid.UUID
    plugin_key: str
    label: str
    config: dict
    credentials: Credentials
```

`create_plugin(connection: ResolvedConnection) -> GrowthOSPlugin` replaces today's
`create_plugin(connection: object)`. A Reddit plugin's `create_plugin` reads
`connection.credentials.access_token` directly — never sees ciphertext, never imports
anything from `backend/app`, never calls a decryption routine. An `api_key`-auth plugin reads
`connection.credentials.api_key` the same way; the shape is uniform across every `auth_type`,
not special-cased for OAuth.

**Where manifest validity (does an `oauth2` plugin actually declare `oauth`?) is checked:**
not in the frozen `PluginManifest` dataclass itself (keeping it a plain, unvalidated data
carrier, consistent with its current design) — in `plugin_catalog.py`'s discovery step,
alongside the existing `interface_version` compatibility check. A manifest declaring
`auth_type="oauth2"` with `oauth=None` fails discovery loudly, the same way an unsupported
`interface_version` does today — logged, excluded from the catalog, never silently accepted.

**The shared contract suite (`plugins/_shared/tests/test_plugin_contract.py`) gains one more
assertion:** if `manifest.auth_type == "oauth2"`, `manifest.oauth` must be a real
`OAuthProviderSpec` with non-empty `authorize_url`/`token_url`. Same spirit as the existing
checks — catch a plugin author's mistake at test time, not at first real connection attempt.

---

## 5. Authentication flow diagrams

### 5.1 First connection

```
Browser              Frontend            GrowthOS API                  Provider
  |                     |                     |                            |
  | click "Connect"     |                     |                            |
  |-------------------->|                     |                            |
  |                     | POST .../oauth/start|                            |
  |                     |-------------------->|                            |
  |                     |                     | build signed state          |
  |                     |                     | (+ PKCE verifier if req'd)  |
  |                     |   {authorize_url}    |                            |
  |                     |<--------------------|                            |
  | redirect to provider|                     |                            |
  |<--------------------|                     |                            |
  |------------------------------------------------------------------------->|
  |                                                              user approves scopes
  |<-------------------------------------------------------------------------|
  | redirect: GET /api/v1/oauth/{plugin_key}/callback?code=..&state=..       |
  |-------------------------------------------->|                           |
  |                                              | verify state (sig, age, user_id match)
  |                                              | exchange code for tokens  |
  |                                              |-------------------------->|
  |                                              |<--------------------------|
  |                                              | envelope-encrypt tokens   |
  |                                              | upsert plugin_connections |
  |                                              | write audit_log           |
  | 302 → frontend success page                  |                          |
  |<----------------------------------------------|                          |
```

### 5.2 Background token refresh (no user involved)

```
Arq periodic job (oauth_refresh)          plugin_connections                 Provider
        |                                        |                              |
        | SELECT ... WHERE token_expires_at       |                              |
        |   < now() + 10m AND status='connected'  |                              |
        |   FOR UPDATE SKIP LOCKED                |                              |
        |----------------------------------------->|                            |
        |  row locked, re-check expires_at         |                            |
        |  (double-checked — see §6 on races)      |                            |
        | POST token_url, grant_type=refresh_token |                            |
        |------------------------------------------------------------------------>|
        |  200 {access_token, new refresh_token?, expires_in}                     |
        |<-------------------------------------------------------------------------|
        | envelope-encrypt, update row, commit     |                            |
        |----------------------------------------->|                            |
        |                                    (or, on invalid_grant/400):
        |  set status='expired', write audit_log, commit — no retry              |
```

### 5.3 Reconnecting an expired connection

Identical to §5.1, except the `POST .../oauth/start` call is made for a `label` that already
has a row in `expired`/`error` status. The callback's upsert updates that row in place —
same `id`, same `config`, same `capabilities_enabled` — rather than creating a second
connection. From the plugin's perspective this is indistinguishable from any other refreshed
credential; `ResolvedConnection.credentials` just has new values the next time it's
constructed.

### 5.4 Disconnect

```
Browser         Frontend         GrowthOS API                    Provider
  |                |                  |                             |
  | click "Disconnect"                |                             |
  |--------------->|                  |                             |
  |                | POST .../disconnect                            |
  |                |----------------->|                             |
  |                |                  | best-effort POST revoke_url  |
  |                |                  |---------------------------->|
  |                |                  |  (failure here doesn't block)|
  |                |                  | clear credentials/expiry/scopes on row
  |                |                  | status='disconnected'        |
  |                |                  | write audit_log              |
  |                |    204            |                             |
  |                |<-----------------|                             |
```

---

## 6. Security considerations

- **State CSRF protection.** The `state` parameter is a signed (itsdangerous — same primitive
  as session tokens, `app/core/security.py`), short-max-age (10 minutes) token, not a bare
  random string checked against server-side storage. It embeds `project_id`, `plugin_key`,
  `label`, `user_id`, a nonce, `issued_at`, and — when PKCE applies — the `code_verifier`.
  **Judgment call #3:** this is deliberately stateless (no `oauth_states` table). The
  signature already provides the CSRF guarantee (an attacker cannot forge a valid state
  without the server's secret key); a DB table would add a write, a read, and a cleanup job
  for zero additional security property. The `code_verifier` inside a signed-but-not-encrypted
  token is not a confidentiality concern: it travels through the browser's redirect chain
  either way (that's inherent to the authorization-code-with-PKCE flow, RFC 7636), and by
  itself it's useless without the single-use authorization code the provider controls.
- **Session binding.** The callback requires both a valid signed state *and* a currently
  authenticated GrowthOS session whose user matches the state's embedded `user_id`. This
  closes a session-fixation-shaped gap: someone else's browser completing a flow you
  initiated (or vice versa) is rejected, not silently honored.
- **PKCE (judgment call, built now, not deferred).** `OAuthProviderSpec.pkce` is a
  three-value policy (`required`/`supported`/`unsupported`), checked per-provider because not
  every provider accepts an unrecognized `code_challenge` param gracefully. Built as a
  first-class part of `OAuthClient` from the start — not a "future" add-on — because X's
  OAuth 2.0 (on your list of target providers) requires it; deferring PKCE would mean
  redesigning the state token (which already carries the verifier) the day X is implemented.
- **Client secrets are operator-level config, not per-connection data.** `{PLUGIN_KEY}
  _OAUTH_CLIENT_ID` / `_CLIENT_SECRET` live in `Settings`/`.env` (same trust tier and same
  "never committed, `.env.example` holds no real values" discipline as `SECRET_KEY` /
  `CREDENTIAL_MASTER_KEY`, per `docs/security/SECURITY.md`) — never in the database, never
  returned by any API response. This matters because a database compromise (even of
  envelope-encrypted rows) should not also mean the OAuth app registration itself is
  compromised.
- **Token storage reuses ADR 0010 exactly** — no new encryption primitive. `access_token`/
  `refresh_token` are JSON-serialized and go through the identical per-connection data-key
  envelope every other credential already uses. The master-key rotation runbook in
  `docs/security/SECURITY.md` needs zero changes to also cover OAuth tokens.
- **Redaction.** `access_token`, `refresh_token`, and `client_secret` are added to
  `app/core/logging.py`'s `_REDACTED_KEYS` set — structured log lines can reference that a
  refresh happened without ever rendering the token value, consistent with the existing
  redaction list.
- **Refresh-race safety.** The background sweep locks each candidate row (`SELECT ... FOR
  UPDATE SKIP LOCKED`) and re-checks `token_expires_at` after acquiring the lock before
  making the network call — a double-checked pattern preventing two concurrent sweep runs (or
  a sweep run overlapping a user-triggered reconnect) from both attempting to consume the
  same (possibly single-use-rotating) refresh token, which would otherwise cause one of the
  two to fail with `invalid_grant` and wrongly mark a perfectly good connection `expired`.
  This is the same category of concern `ContentItem.version` already exists to close
  (`ARCHITECTURE.md` §8, LOCKED_DECISIONS L12) — a concurrent-transition race, addressed the
  same way: a lock at the point of transition, not hope.
- **Redirect URI exact-match.** The registered `redirect_uri` sent on every authorize/token
  call is a single fixed, configured value per plugin (§3) — never influenced by request
  data — closing the standard OAuth open-redirect-via-callback class of issue.
- **Revocation is best-effort, never blocking.** Disconnect always succeeds locally
  (credentials cleared, status updated) even if the provider's `revoke_url` is unreachable or
  errors — a user must always be able to disconnect from GrowthOS's side regardless of the
  provider's availability.
- **Audit trail.** `oauth_connected`, `oauth_reconnected`, `oauth_refresh_failed` (permanent
  failures only — not every transient retry), and `oauth_disconnected` all write `audit_log`
  rows, extending the existing "connecting, disconnecting, or reconfiguring a plugin
  connection writes an audit_log row" line already in `docs/auth/AUTHENTICATION.md`.
- **Trust model unchanged.** This design does not touch `ARCHITECTURE.md` §5's plugin trust
  model (first-party, reviewed plugin code only, full process access, no sandboxing). A
  malicious plugin could still misuse a `ResolvedConnection` it's handed — that's already the
  accepted, explicitly-stated limit, not something this design pretends to close.

---

## 7. Migration impact

- **Schema:** the migration in §2. The `ALTER TYPE ... ADD VALUE` step must run in its own
  migration (or with `op.execute(...)` outside an implicit transaction, depending on the
  Postgres version) — Postgres historically disallows using a freshly-added enum value in the
  same transaction that added it. Two small migrations (enum value, then columns +
  constraint) avoids the issue entirely rather than fighting it.
- **Config:** new `Settings` fields — per-plugin OAuth client credentials (naming convention
  `{PLUGIN_KEY}_OAUTH_CLIENT_ID`/`_CLIENT_SECRET`, loaded the same way existing per-integration
  secrets are), the fixed OAuth callback base URL, and the fixed post-callback frontend
  redirect URL. All additive to `docs/config/CONFIGURATION.md`; no existing setting changes
  meaning.
- **SDK — one breaking change, currently harmless.** `create_plugin()`'s signature changes
  from `(connection: object)` to `(connection: ResolvedConnection)`. This is breaking in
  principle but affects zero real plugins today — only `plugins/dummy/` (a test fixture)
  implements `create_plugin` at all. `plugins/dummy/plugin.py`,
  `plugins/dummy/tests/test_contract.py`, and `scripts/new_plugin.py`'s generated template
  all need a one-line signature update as the first implementation step, before any OAuth
  code is written — this is the same category of "safe because nothing real exists yet"
  change already made once for `WebhookReceivable` (Platform Improvement pass).
- **New background job.** One new Arq periodic job (`oauth_refresh`, alongside the existing
  event-dispatcher and scheduler periodic jobs — no new job *infrastructure*, just one more
  job function registered in `app/jobs/`).
- **New service.** `OAuthConnectionService` (start/callback/disconnect orchestration),
  separate from the existing `PluginConnectionService` (generic create/list, still used
  as-is for non-OAuth `auth_type`s) rather than overloading one service with two different
  responsibilities.
- **Docs to update once implemented (not part of this design turn):**
  `docs/auth/AUTHENTICATION.md`'s one-sentence OAuth stub, `docs/plugins/PLUGIN_ARCHITECTURE.md`
  (manifest example, credentials section), `docs/api/API_DESIGN.md` (new routes),
  `docs/plugins/QUICKSTART.md` (an OAuth-specific walkthrough section), `docs/security/SECURITY.md`
  (extend the master-key rotation runbook to note OAuth tokens ride the same mechanism).
- **Nothing about this migration requires downtime or a data backfill** — every new column
  has a safe default (`label` defaults `'default'`, `token_expires_at`/`granted_scopes`
  default null/empty), and zero existing rows use `auth_type="oauth2"` yet (no plugin
  implementation exists), so there is no existing OAuth data to migrate.

---

## 8. Step-by-step implementation plan

Sequenced so each step is independently testable before the next begins; Reddit itself is
deliberately last.

1. **Schema migration** — §2's DDL, plus the `PluginConnectionResponse` schema additions
   (`label`, `token_expires_at`, `granted_scopes`).
2. **SDK additions** — `plugins/_shared/oauth.py`, `plugins/_shared/credentials.py`,
   `ResolvedConnection` in `base.py`, `PluginManifest.oauth` field. Update `plugins/dummy/`
   and `scripts/new_plugin.py`'s templates for the new `create_plugin()` signature. Extend
   `test_plugin_contract.py`'s assertions (§4). All independently testable with zero platform
   OAuth code written yet.
3. **`plugin_catalog.py` validation** — reject an `oauth2` manifest missing `oauth` at
   discovery time, mirroring the existing `interface_version` check.
4. **`backend/app/core/oauth/`** — `pkce.py`, `state.py`, `client.py` (authorize-URL
   building, code exchange, refresh, revoke), `errors.py`. Unit-testable against a fake HTTP
   provider (`httpx`'s mock transport) with zero database or API involvement.
5. **Settings** — OAuth client credential loading, callback base URL, post-callback
   frontend URL.
6. **`OAuthConnectionService`** — start/callback/disconnect, envelope encryption reuse,
   audit logging. Integration-testable against a fake provider end-to-end (authorize →
   callback → connected row → decrypt round-trip).
7. **API routes** — `oauth/start`, the global `oauth/{plugin_key}/callback`,
   `oauth/disconnect`. Integration tests covering: fresh connect, reconnect of an
   `expired` row, state-tampering rejection, session-mismatch rejection, disconnect with a
   reachable and an unreachable `revoke_url`.
8. **`oauth_refresh` Arq periodic job** — the locking/double-check pattern from §6,
   transient-vs-permanent failure handling, transition to `expired` on `invalid_grant`.
   Tested for the concurrent-refresh race explicitly (two simulated workers, one refresh
   token, assert only one attempt reaches the provider).
9. **`PluginRegistry._load_plugin_instance()` integration** — decrypt, build
   `ResolvedConnection`, pass to `create_plugin()`. This is the point where OAuth plugins
   become constructible at all; test against the updated `dummy` fixture plus a second
   OAuth-shaped test fixture plugin (not Reddit — a fixture, same spirit as `plugins/dummy`)
   exercising the full `ResolvedConnection.credentials` path.
10. **Docs** — the "once implemented" list in §7, plus `docs/plugins/QUICKSTART.md`'s OAuth
    walkthrough.
11. **Only then: the Reddit plugin.** Reddit's `manifest.py` declares its
    `OAuthProviderSpec`; `plugin.py` reads `connection.credentials.access_token`. If this
    framework is designed correctly, Reddit-specific code should be almost entirely PRAW
    integration and `search()`/`publish()` logic — near-zero OAuth code, because there isn't
    supposed to be any left to write.

Every provider on your list beyond Reddit (Google Search Console/Analytics, LinkedIn, X,
GitHub, Slack, Discord, Notion, HubSpot, Stripe) becomes step 11 repeated with a different
manifest and a different HTTP client for that provider's actual API — never a repeat of
steps 1–9.
