# Platform Improvement Report

**Date:** 2026-07-25
**Scope:** every improvement from `docs/reviews/PLATFORM_READINESS_REVIEW.md`'s priority-ranked
checklist that belongs *before* Plugin #1, excluding OAuth integrations, AI providers,
Conversation Finder, Content Agent, and any plugin-specific business logic — all explicitly
out of scope for this pass. Architecture stays frozen; nothing here changes a locked decision
or an ADR.

---

## 1. Platform Improvement Report

Every item survived without touching the frozen architecture. The pattern across all of them:
the *mechanism* (manifest, Protocols, registry, two-gate enforcement) was already solid — what
was missing was the developer-facing surface around it: infrastructure the docs promised but
that didn't exist, one real structural gap in the SDK contract, and a handful of DX/tooling
gaps. All of it closes without a redesign.

**Verification, run at the end of this pass:**

- `python scripts/lint.py` (ruff + mypy --strict against `backend/`) — clean.
- Full backend test suite: **88 passed** (67 from Phase 1 + 21 new backend tests).
- Plugin SDK test suite (`plugins/_shared/tests`, `plugins/dummy/tests`, run from the repo
  root per the new root `pyproject.toml`): **12 passed** — all new.
- `ruff` + `mypy --strict` against `plugins/_shared/` and `plugins/dummy/` directly (not
  covered by `scripts/lint.py` — see §3): clean.
- The scaffolding script (`scripts/new_plugin.py`) was exercised end-to-end three times
  during this work — generating every single-capability plugin, one plugin with all four
  capabilities, and the exact quickstart walkthrough — each time installed editable, linted,
  type-checked, and run through `pytest`, then removed. All three passed clean.

**30 new tests, 0 regressions.** Nothing from Phase 1's 67 tests was touched or needed
changing.

---

## 2. List of implemented improvements

Mapped to the review's priority-ranked checklist (§6 of
`docs/reviews/PLATFORM_READINESS_REVIEW.md`); item 1 (OAuth2 flow) is intentionally absent —
excluded by this task's explicit scope.

| # | Item | What changed |
|---|---|---|
| 2 | `WebhookReceivable` event-publishing gap | New `plugins/_shared/events.py`: a dependency-free `DomainEventPublisher` Protocol. `WebhookReceivable.handle_webhook()` now takes `events: DomainEventPublisher`. `app.core.events.EventPublisher` satisfies it structurally (proven by test) — a `WebhookReceivable` plugin now has a real, legal way to do what the docs always said it must. |
| 3 | Plugin-connection API + config validation | `POST`/`GET /api/v1/projects/{project_id}/plugin-connections` (`app/api/v1/plugin_connections.py`, `app/services/plugin_connection.py`). Validates `config` against the plugin's own `config_schema` (direct pydantic validation — no new JSON-Schema-validator dependency needed, since the manifest already holds the real pydantic class). Rejects unknown `plugin_key`, undeclared capabilities, duplicate connections. Writes an `audit_log` row (`docs/auth/AUTHENTICATION.md` already promised this; nothing had implemented it). |
| 4 | Missing promised test/rate-limit infra | `plugins/_shared/tests/test_plugin_contract.py` (real now, not a stale reference) and `plugins/_shared/rate_limit.py` (in-process token bucket) both exist and are tested. |
| 5 | `plugins/dummy` had no tests | `plugins/dummy/tests/test_contract.py`, plus a new root-level `pyproject.toml` so a plugin's own tests are runnable standalone (`pytest plugins/dummy/tests`) without `cd`-ing into `backend/`. |
| 6 | No plugin quickstart tutorial | `docs/plugins/QUICKSTART.md` — a linear, runnable walkthrough, every command verified against this real repo, distinct from `PLUGIN_ARCHITECTURE.md`'s design-rationale doc. |
| 7 | No scaffolding tool | `scripts/new_plugin.py <name> [--capabilities ...] [--auth-type ...]` — generates a full plugin package (manifest, Protocol-stub `plugin.py`, `pyproject.toml` with the packaging trick already correct, `README.md`, `tests/`). Verified against every capability combination. |
| 8 | Stale path references | `plugin_registry.py`'s docstring and `plugins/_shared/base.py`'s module docstring both pointed at `backend/tests/fixtures/dummy_plugin`, which never existed — fixed to point at `plugins/dummy/`. |
| 9 | `interface_version` exact-string allowlist | Replaced with a documented major-version-compatible check (`_interface_version_is_compatible` in `plugin_catalog.py`) — same-major-any-minor is compatible, matching the convention now written into `PLUGIN_ARCHITECTURE.md` §Interface versioning. |
| 10 | `get()` vs `all_with_capability()` inconsistency | Not unified — documented as an intentional asymmetry (fail-fast for a specific lookup vs. resilient for fan-out), with a docstring on each method explaining why, and a structured warning log added where `all_with_capability()` skips a broken plugin (previously silent). |
| 11 | `client.py` required but unused | Dropped from both "how to add a plugin" checklists (`CONTRIBUTING.md`, `PLUGIN_ARCHITECTURE.md`) — now documented as an optional convention, matching what the scaffolding tool and the only real example actually do. |
| 12 | No re-export surface | `plugins/_shared/__init__.py` now re-exports the SDK's common types — `from plugins._shared import PluginManifest, Searchable, ...` instead of four separate submodule imports. Also fixed the manifest example in `PLUGIN_ARCHITECTURE.md`, which imported from a package (`growthos.plugins`) that has never existed. |

**One item beyond the checklist**, found while implementing #3: `AUTHENTICATION.md` already
documented "connecting a plugin connection writes an audit_log row" — nothing did. Implemented
alongside the connection API rather than left as a second, separate doc/code mismatch.

---

## 3. Architectural decisions that required clarification

**None required stopping to ask** — every choice below was a normal engineering decision
inside the frozen architecture's existing latitude, not a change to a locked decision. Listed
here for visibility, since several are worth knowing about even though they didn't block:

- **`WebhookReceivable.handle_webhook()`'s signature changed** (added `events:
  DomainEventPublisher`). This is technically a breaking SDK change, but zero real plugins
  implement it yet (only the design-review-identified gap made it impossible to implement
  correctly at all) — closing the gap was the point, not something to defer for
  approval.
- **Interface-version compatibility policy** (major-version match). `PLUGIN_ARCHITECTURE.md`
  explicitly deferred this ("should be documented ... once the first breaking change is
  actually being planned — not speculatively now"). I judged implementing the *mechanism*
  (a standard, reversible semver-major convention) as safe and non-speculative — it changes
  nothing about currently-installed plugins (only `"1.0"` exists anywhere) and is trivially
  revisable. The *policy* question the doc actually deferred — how long an old major version
  stays supported, whether two majors are ever supported side by side — is still open and
  still deferred; I did not decide that.
- **Rate limiter is in-process, not Redis-backed**, despite `PLUGIN_ARCHITECTURE.md`
  previously saying "backed by Redis." The doc's claim was aspirational, not implemented
  infrastructure. An in-process token bucket keeps the SDK dependency-free (an explicit
  instruction for this task) and is honestly sufficient for the current single-process
  deployment; I documented the known limitation (effective rate scales with replica count)
  rather than silently matching the old doc's Redis claim with a redis-py dependency the SDK
  didn't need.
- **Plugin-connection config validation uses pydantic directly**, not a JSON-Schema validator
  library. `PluginManifest.config_schema` already holds the real pydantic class in-process
  (not just its derived JSON Schema), so `model_validate()` is strictly more correct and adds
  zero new dependencies — a straightforward implementation choice, not a design question.
- **`scripts/lint.py` was reverted, not extended.** I initially tried making it actually lint
  `agents/`/`plugins/` (matching its own docstring's existing claim). This surfaced pre-existing
  lint findings in files I hadn't touched (`agents/_shared/base.py`,
  `backend/app/core/subscriptions.py`, others) purely as an artifact of ruff's import-sorting
  behavior changing under a different invocation `cwd` — not real problems with that code.
  Fixing it properly would mean either accepting that churn or tuning ruff's first-party-import
  detection, both bigger than this task's scope. I reverted the implementation and fixed only
  the docstring's false claim instead — see §4.

None of these touch a `docs/decisions/` ADR or `ARCHITECTURE.md` §2's five guiding
constraints.

---

## 4. Remaining items intentionally deferred until Plugin #1

- **OAuth2 connection flow** — explicitly excluded from this task. This is the actual blocker
  for Reddit specifically (see §5).
- **Webhook ingress route** (`POST /webhooks/{plugin_key}`) — the SDK-side contract is fixed
  and tested (§2, item 2), but the route that would resolve a connection and actually call
  `handle_webhook()` doesn't exist. Not needed for Reddit; needed before `email`/`slack`/
  `discord`.
- **Credential encryption implementation** — `plugin_connections.credentials_encrypted` /
  `credential_data_key_wrapped` columns exist; no encrypt/decrypt code exists. The new
  connection-creation endpoint deliberately does not touch credentials at all (see its schema
  docstring) — wiring real credentials into a connection, for any `auth_type`, is still
  unbuilt.
- **The interface-version *deprecation* policy** (how long an old major stays supported) —
  see §3; the mechanism is built, the policy isn't decided.
- **`scripts/lint.py` covering `agents/`/`plugins/`** — attempted, reverted; see §3. The
  docstring now accurately says what it checks and points at the direct `ruff`/`mypy` commands
  for linting a plugin yourself (also in `docs/plugins/QUICKSTART.md`).

---

## 5. Final assessment: is the platform ready for the Reddit plugin?

**Ready for a generic (non-OAuth) plugin: yes.** A developer building any plugin with
`auth_type="api_key"` or `"session_credentials"` today has: a scaffolding tool that generates
a clean, lint-passing starting point in one command; a real quickstart that's been run
end-to-end against this exact repo; a way to actually connect their finished plugin to a
project via the API; a real, runnable contract test suite; a rate limiter; and accurate docs
that no longer promise infrastructure that isn't there.

**Not ready for Reddit specifically — and only for the one reason this task deliberately left
standing.** Reddit's manifest declares `auth_type="oauth2"`
(`plugins/reddit/README.md`). This task explicitly excluded OAuth integrations, so the actual
blocker identified in the readiness review — "design and document plugin OAuth2 flow" — is
still exactly where it was: undesigned. Every other item on the pre-Plugin-1 punch list is
closed.

**Recommendation:** the next real decision point is OAuth2, not more platform-readiness work.
Reddit implementation can begin as soon as that flow is designed (redirect/callback endpoint,
where `authorize_url`/`token_url`/`client_id` live, state-param handling, token refresh) —
which was always flagged as a design decision needing your input before any code, per the
original review.
