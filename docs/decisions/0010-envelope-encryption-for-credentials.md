# ADR 0010: Envelope encryption for plugin credentials

**Status:** Accepted — 2026-07-25

## Context

`plugin_connections.credentials_encrypted` was designed to be encrypted directly under one
static, application-layer symmetric key (`CREDENTIAL_ENCRYPTION_KEY`, a bare `.env` value).
A design review (`docs/reviews/DESIGN_REVIEW.md` §5.1) flagged this as the highest-severity
security finding in the system: this single key decrypts every plugin credential — Reddit,
LinkedIn, email, and eventually up to 100+ plugins' worth — for every connected project, with
no described rotation path. In practice, "rotate the key" would mean re-encrypting every
stored credential in one operation, which in practice means it never happens, leaving a
long-lived single point of total credential compromise.

## Decision

Adopt envelope encryption. A **master key** (operator-held via the deployment platform's
secret store initially; a cloud KMS is a compatible future upgrade, not a redesign) encrypts
a unique, randomly generated **data key** per `plugin_connections` row. The data key —
not the master key — encrypts that row's actual credential material. The wrapped
(master-key-encrypted) data key is stored alongside the credential ciphertext.

## Consequences

**Positive:** master-key rotation becomes re-wrapping every stored data key under the new
master key — a fast operation touching small values, not re-encrypting potentially large
credential payloads across every connection. This makes rotation something that can actually
happen on a schedule or in response to a suspected leak, rather than a theoretical capability
nobody exercises. `docs/security/SECURITY.md`'s incident-response runbook gets a concrete,
executable procedure instead of an implied one.

**Accepted trade-off:** more moving parts than direct symmetric encryption — a data-key
generation and wrapping step on every new connection, and a small amount of additional
storage (the wrapped data key) per row. Judged clearly worth it given what this key
protects: credentials capable of posting publicly and messaging real people under the
founder's identity, across a plugin surface explicitly designed to grow to 100+.

**Deliberately not decided here:** where the master key itself lives (local secret store vs.
cloud KMS) is left flexible — see `docs/architecture/LOCKED_DECISIONS.md` §2. This ADR locks
the *pattern* (envelope encryption, rotatable master key), not the specific key-management
product, so that choice can be made when there's an actual deployment target to make it
against.
