# ADR 0011: Generic OAuth2 framework in the platform layer, not per-plugin

**Status:** Accepted — 2026-07-25.

## Context

`docs/auth/AUTHENTICATION.md` has, since Phase 0, described plugin OAuth as "the standard
OAuth2 authorization-code flow, with the resulting tokens encrypted at rest" — one sentence,
no mechanism. The Platform Readiness Review
(`docs/reviews/PLATFORM_READINESS_REVIEW.md` §1, §4) identified this as the concrete blocker
for Reddit (`auth_type="oauth2"`, ADR 0005) and every other OAuth-capable provider on the
stated roadmap: Google Search Console, Google Analytics, LinkedIn, X, GitHub, Slack, Discord,
Notion, HubSpot, Stripe, and any future provider.

The question this ADR answers: where does OAuth2 protocol logic live — inside each plugin
package, or as a generic platform subsystem every OAuth-capable plugin declares metadata
against?

## Decision

OAuth2 logic lives entirely in the platform (`backend/app/core/oauth/`), never inside a
plugin package. A plugin declares an `OAuthProviderSpec` (authorize/token/revoke URLs,
scopes, PKCE policy, provider-specific extra params) as manifest metadata — the same pattern
already locked in for capabilities (ADR 0007), content types (ADR 0008), and config schema
(ADR 0009): a plugin describes itself declaratively; the platform executes generically
against that description. No plugin ever builds an authorize URL, exchanges a code, or
refreshes a token itself.

Concretely (full detail in `docs/auth/OAUTH2_ARCHITECTURE.md`):

- A generic, provider-agnostic `OAuthClient` executes RFC 6749 (with optional RFC 7636 PKCE)
  against whatever `OAuthProviderSpec` a plugin's manifest declares.
- OAuth state is a signed, stateless, time-limited token (reusing the existing
  `itsdangerous`-based session-token pattern), not server-side session storage.
- Token storage reuses ADR 0010's envelope-encryption pattern exactly — no new encryption
  primitive.
- Token refresh is an Arq periodic job (reusing ADR 0002's job infrastructure), never a
  synchronous user-facing call.
- `plugin_connections` gains a `label` column (supporting multiple connections to the same
  plugin within one project) and an `expired` status value (distinguishing "will
  self-heal via refresh" from "needs human re-authorization").
- `create_plugin()`'s factory signature changes to receive a typed, already-decrypted
  `ResolvedConnection` instead of the raw ORM row — closing the gap where a plugin would
  otherwise need to handle ciphertext or import `backend/app`'s decryption code directly.

## Consequences

**Positive:** implementing OAuth once, generically, means every one of the 12 named
providers — and any future one — is a manifest (data) plus that provider's own API client
code, not a reimplementation of the authorization-code flow, token refresh, CSRF state
handling, and envelope encryption integration each time. This is the direct continuation of
the reasoning that produced ADR 0007/0008/0009: a 100+-plugin system cannot afford a
per-plugin reimplementation of anything that is actually the same mechanism with different
parameters.

**Accepted trade-off:** `create_plugin()`'s signature change is technically breaking.
Accepted because zero real plugins exist yet — only the `plugins/dummy/` test fixture
implements it — making this the cheapest possible moment to make the change, exactly as
reasoned when `WebhookReceivable`'s signature was fixed in the Platform Improvement pass.

**Deliberately not decided here:**
- Where OAuth app registration secrets (`client_id`/`client_secret` per provider) are
  stored beyond "operator-level config, not the database" — local `.env` vs. a secret
  manager is the same flexible question ADR 0010 already left open for the master key
  itself (`docs/architecture/LOCKED_DECISIONS.md` §2), and is answered the same way here:
  the pattern is locked, the specific secret-storage product isn't.
- Whether a future multi-tenant deployment (Phase 4) needs per-org OAuth app registrations
  instead of one shared GrowthOS-operated app per provider — out of scope for a solo-first
  v1, consistent with ADR 0001.

## Alternatives considered

- **Per-plugin OAuth implementation** (each plugin's own `client.py` makes its own token
  endpoint calls). Rejected: this is the "if you find yourself writing X inside a plugin, the
  abstraction is wrong" pattern (`ARCHITECTURE.md` §1) applied to OAuth — 12+ near-identical,
  independently-buggy implementations of RFC 6749 instead of one reviewed one.
- **A server-side OAuth state table.** Rejected in favor of a signed, stateless state token:
  no additional security property over a signature-verified token, at the cost of a write,
  a read, and a cleanup job. See `docs/auth/OAUTH2_ARCHITECTURE.md` §6.
- **Keeping one connection per (project, plugin_key)**, i.e. not adding `label`. Rejected:
  real cases on the target provider list (two Reddit accounts, two Slack workspaces) need
  more than one connection to the same plugin within a single project; `label` closes this
  without weakening any existing gate (capability enablement, config validation) or touching
  the org/project tenancy model.
