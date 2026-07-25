# Security Considerations

**Version 2** — updated after the Principal Engineer design review
(`docs/reviews/DESIGN_REVIEW.md` §5) identified the single highest-severity finding in the
system here: a static, unrotatable credential encryption key. This version replaces that with
envelope encryption and adds the audit log, brute-force protection, and explicit plugin
trust-model statement the review also called for.

## Threat model, briefly

GrowthOS holds two categories of especially sensitive data: (1) credentials for external
accounts (Reddit, LinkedIn, email, etc.) capable of posting publicly or messaging real
people under the founder's identity, and (2) a growing knowledge base of business-sensitive
market research. The primary threats this design defends against are credential
exfiltration and unauthorized publishing — not, at this stage, nation-state-level threats or
protection against a fully compromised host, which is out of scope for a single-operator
system's threat model.

## Plugin credential encryption: envelope encryption

`plugin_connections.credentials_encrypted` is protected by **envelope encryption**, not
direct encryption under one static key:

- A **master key** (operator-held via the deployment platform's secret store; a cloud KMS is
  a compatible future upgrade, not a redesign) never touches a credential directly.
- Each `plugin_connections` row gets a unique, randomly generated **data key** at connection
  time. The data key encrypts that row's actual credential (AES-GCM); the master key encrypts
  (wraps) the data key. Both the credential ciphertext and the wrapped data key are stored on
  the row (`credentials_encrypted`, `credential_data_key_wrapped`).
- The database itself never holds plaintext credentials or an unwrapped data key — a database
  backup leak or a read-replica misconfiguration doesn't directly expose them.
- Decryption happens only inside plugin instance construction
  (`docs/plugins/PLUGIN_ARCHITECTURE.md`), scoped to the request/job that needs it —
  credentials are never logged (`docs/logging/LOGGING.md`) and never returned by any API
  response, including to the authenticated owner.

**Why this over a single static key (the original design):** rotation. With one static key,
rotating it means re-encrypting every stored credential across every connection in one
operation — in practice, an operation that never happens, leaving a long-lived single point
of total credential compromise. With envelope encryption, rotation means re-wrapping every
stored data key under a new master key — fast, touches no actual credential ciphertext, and
is small enough to actually run on a schedule or in response to a suspected leak. See
`docs/decisions/0010-envelope-encryption-for-credentials.md`.

### Master key rotation runbook

1. Generate a new master key; store it as the new "current" key.
2. Run the rewrap job: for every `plugin_connections` row, decrypt
   `credential_data_key_wrapped` with the *old* master key, re-encrypt (wrap) it with the
   *new* one. This touches only the small wrapped-data-key value, never the credential
   ciphertext itself.
3. Verify: spot-check a sample of connections decrypt correctly end-to-end (data key unwraps,
   credential decrypts) under the new master key.
4. Retire the old master key.

This is the concrete procedure that replaces the previous version's unresolved "rotation is
undefined" gap — it should be exercised at least once in staging before the first real
production credential is ever stored, so it's a tested runbook, not a theoretical one.
`app/core/crypto.py` implements the primitive this runbook needs (`rewrap_data_key`) — an
operational rotation job/script that walks every row and calls it is not itself built yet
(out of scope for the OAuth2 framework; see `docs/reviews/OAUTH_IMPLEMENTATION_REPORT.md`).

**OAuth2 tokens use this exact mechanism, not a separate one.** `app/services/
oauth_connection.py` calls the same `envelope_encrypt`/`envelope_decrypt` every other plugin
credential uses — an access/refresh token pair is JSON-serialized and encrypted like any
other credential payload. See `docs/auth/OAUTH2_ARCHITECTURE.md` §6 for OAuth-specific
considerations layered on top of this (CSRF-protected state, PKCE, redirect URI validation,
best-effort revocation on disconnect, refresh-race safety) — none of them change how
credentials are actually stored at rest.

## The approval gate is the primary security control, not just a UX feature

Reframing `ARCHITECTURE.md` §8 in security terms: the `ContentItem` state machine is what
prevents a prompt-injection attack (a malicious forum post crafted to manipulate an agent's
LLM call into drafting something harmful) or a bug in an agent's prompt from ever resulting
in real-world published harm. Even a fully compromised or misbehaving agent can only ever
produce a `pending_review` draft — it has no code path capable of reaching `published`. This
is why `docs/testing/TESTING.md` holds `ContentApprovalService` to a 100%-branch-coverage bar:
it is the actual security boundary, not just business logic. Its concurrency guard (the
`version` column, `ARCHITECTURE.md` §8) is part of this boundary, not a separate correctness
nicety — a race that let two approvals or an approve-and-reject race both succeed would be a
security-relevant bug, not just a UX glitch.

## Prompt injection awareness

Content agents process untrusted external text (forum posts, comments) as LLM input. Two
mitigations: (1) the approval gate above, which bounds worst-case impact to "a bad draft a
human rejects," and (2) `content_agent`'s self-check (banned-phrase filter, length limits,
`docs/agents/AGENT_ARCHITECTURE.md`) as a first-pass filter before anything reaches a human at
all — not a security guarantee by itself, but a reduction in reviewer fatigue that keeps the
human-in-the-loop control actually effective rather than something that gets rubber-stamped
out of review fatigue.

## Plugin trust model — stated explicitly, not implicit

Plugins execute as in-process Python code with full process access: they can read
environment variables (including the master key itself, if the process holding it also loads
plugin code — see below), and nothing structurally isolates one plugin's execution from
another's or from core. **The current design assumes every installed plugin is first-party,
code-reviewed code written or reviewed line-by-line by the GrowthOS maintainer.** This is a
reasonable trust model for a handful of plugins at that provenance. It is explicitly **not**
a safe trust model for accepting plugins from unknown or unvetted authors — a real isolation
boundary (subprocess execution, capability-restricted sandboxing, a plugin process that
cannot read the encryption master key at all) is a hard prerequisite before that ever
happens, not an enhancement to add later once it's already happening. See
`docs/plugins/PLUGIN_ARCHITECTURE.md` §Trust model and
`docs/architecture/LOCKED_DECISIONS.md` §2.

## Authentication hardening

- **Brute-force protection.** Login attempts are rate-limited per account and per source IP
  (exact mechanism — sliding-window limiter vs. progressive lockout — left as an
  implementation detail; see `docs/architecture/LOCKED_DECISIONS.md` §2). Given a
  compromised session is a path to every connected plugin's credentials (mediated through
  envelope encryption, not directly, but still reachable via the running application), "good
  password hashing" alone (Argon2id, `docs/auth/AUTHENTICATION.md`) was judged insufficient
  on its own.
- **Security audit log.** The `audit_log` table (`docs/database/SCHEMA.md`) records
  account-level security events — login, plugin connect/disconnect, credential rotation,
  settings changes — separately from `content_items`' human-approval trail, which exists for
  a different purpose (proving a specific human approved specific content, not reconstructing
  an incident timeline).

## Tenant isolation

v1 (solo-first) enforces project scoping at the application/service layer — every query
filtered by `project_id`, every route behind `require_project_access`
(`docs/auth/AUTHENTICATION.md`). Postgres Row-Level Security is deliberately deferred to
Phase 4: with a single org, RLS adds operational complexity (policy management, connection
role configuration) without a corresponding risk reduction, since there's no second tenant to
isolate from yet. When Phase 4 activates real multi-tenancy, RLS policies should be added as
defense-in-depth underneath the existing application-layer scoping, not as a replacement for
it — see `docs/decisions/0001-multi-tenancy.md`.

## Dependency and secret hygiene

- Dependabot (or equivalent) on `backend/` (pip), `frontend/` (npm), and every `plugins/*/`
  package independently, since a 100+-plugin surface multiplies the dependency graph
  materially — see `docs/scalability/SCALABILITY.md`.
- `.env` files never committed; `.env.example` holds no real values, checked in CI
  (`docs/config/CONFIGURATION.md`).
- Pre-commit hook scanning for accidentally-staged secrets (e.g. `detect-secrets`), on top of
  code review vigilance — not a replacement for it.

## Web-facing surface

The frontend and API are the only components exposed to the public internet; Postgres, Redis,
and the worker processes are internal-network-only in every environment. Webhook ingress
(`/webhooks/{plugin_key}`) is the one unauthenticated-at-the-HTTP-layer endpoint, secured by
per-provider payload verification (`docs/plugins/PLUGIN_ARCHITECTURE.md`) and rate-limited to
mitigate abuse of the endpoint itself.

## Incident response

Two runbooks should exist and be exercised at least once in staging before real plugin
credentials are ever connected in production:

1. **Leaked master key or suspected credential compromise:** execute the master-key rotation
   runbook above, force-reconnect all plugins whose credentials predate the rotation, review
   `audit_log` and recent `content_items`/`agent_runs` for unauthorized activity.
2. **Compromised user session:** invalidate all sessions, force password reset, review
   `audit_log` for the account's recent actions.
