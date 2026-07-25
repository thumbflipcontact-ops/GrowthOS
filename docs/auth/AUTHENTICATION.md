# Authentication & Authorization Strategy

## Principals

Two distinct kinds of caller ever hit the API, and they are never conflated:

1. **Human users**, authenticated with a session, acting through the frontend — the only
   principal allowed to approve/reject `content_items` (see `docs/api/API_DESIGN.md`).
2. **Service callers** — the orchestrator/workers calling internal service methods directly
   (not over HTTP, so not part of this document's threat model) and, at the HTTP boundary,
   plugin webhook ingress, which is authenticated per-plugin (signature verification) rather
   than via GrowthOS's own auth system.

There is no API-key principal with write access to approval endpoints in v1 — deliberately,
since an API key is exactly the kind of credential that could end up embedded in a script
that "helps out" by auto-approving content, which is the one thing this system must never
allow.

## Session strategy

Email + password (Argon2id hashing) for v1, session via an HTTP-only, `Secure`,
`SameSite=Lax` cookie holding a signed session token — not a bare JWT in local storage. This
avoids XSS-exposed token theft being enough to act as the user, at the cost of needing CSRF
protection on state-changing requests (standard double-submit token, applied at the API
layer). Login attempts are additionally rate-limited (per account and per source IP) — see
`docs/security/SECURITY.md` §Authentication hardening — and every login, successful or not,
writes an `audit_log` row.

**Why not SSO/OAuth login from day one:** with one user, building a Google/GitHub OAuth login
flow is pure overhead for zero benefit — password auth behind a session cookie is the
simplest thing that's actually secure. SSO is a natural Phase 4 (multi-tenant activation)
addition, not a v1 requirement — see `ROADMAP.md`.

## Authorization model

- `memberships.role` (`owner` | `member`) scopes what a user can do within an org. v1 has
  exactly one membership row, always `owner`. Every authorization check still goes through
  the same role check that will matter once `member` accounts exist — there is no
  "single-user mode" code path that bypasses the role system, since that bypass is exactly
  the kind of shortcut that becomes a security hole once Phase 4 introduces real multi-user
  orgs.
- All authorization is **org-and-project scoped**: a request for
  `/projects/{project_id}/...` first resolves whether the authenticated user has a
  membership in that project's org, before any resource-specific logic runs. This check lives
  in one FastAPI dependency (`require_project_access`), used by every project-scoped route —
  one place to get this right, not one per endpoint.

## Plugin credentials vs. user authentication

These are different things and are stored differently. User authentication is about who's
allowed to use GrowthOS; plugin credentials (`plugin_connections.credentials_encrypted`,
protected by envelope encryption) are about what GrowthOS is allowed to do on external
systems on the user's behalf. A compromised GrowthOS session should not, by itself, be
enough to exfiltrate plugin credentials in plaintext; decryption happens only inside the
plugin instance construction path (`app/core/plugin_registry.py`,
`docs/plugins/PLUGIN_ARCHITECTURE.md`), not as part of any read endpoint's response.
Connecting, disconnecting, or reconfiguring a plugin connection writes an `audit_log` row.

**Plugin OAuth flows** (connecting a Reddit/LinkedIn/Slack/etc. account) use a generic,
provider-agnostic OAuth2 subsystem (`app/core/oauth/`), not per-plugin OAuth code — see
`docs/auth/OAUTH2_ARCHITECTURE.md` and ADR 0011 for the full design, and
`docs/reviews/OAUTH_IMPLEMENTATION_REPORT.md` for what's actually built. Summary:

- The authorization-code flow runs against whatever `authorize_url`/`token_url` a plugin's
  manifest declares (`OAuthProviderSpec`), with optional PKCE (RFC 7636) per-provider.
- CSRF protection is a signed, stateless, 10-minute state token (same `itsdangerous`
  mechanism as the session cookie above, different payload and salt) — not server-side
  session storage. The OAuth callback additionally requires the state's embedded `user_id`
  to match the currently authenticated session.
- The callback route (`GET /api/v1/oauth/{plugin_key}/callback`) is deliberately **not**
  project-scoped in its path, unlike every other plugin-connection route — a provider's
  registered `redirect_uri` must be one fixed URL; project/plugin/label identity travels
  inside the signed state instead.
- Resulting tokens are envelope-encrypted exactly as any other plugin credential (this
  section, ADR 0010) — no separate encryption path for OAuth.
- Token refresh is an internal background job (`app/jobs/oauth_refresh.py`), never triggered
  by a user-facing request — there is no refresh endpoint.
- A permanent refresh failure (the refresh token itself revoked/expired) transitions the
  connection to a distinct `expired` status, separate from the general `error` status, so a
  "needs reconnect" UI state is queryable rather than inferred from free-form error text.

## Webhook authentication

Not GrowthOS session-based at all — each plugin verifies inbound webhooks using that
provider's own mechanism (HMAC signature, shared secret) before any payload is trusted. See
each plugin's `README.md`.

## What's deferred to Phase 4

- Org invitations, `member` role actually being assignable to a second user.
- SSO/OAuth login.
- Fine-grained per-resource permissions beyond `owner`/`member` (e.g. "can approve content
  but not manage plugin connections") — not needed until there's a second real user whose
  access should be limited.
- API keys for any future public/partner API surface.
