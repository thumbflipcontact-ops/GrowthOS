# GrowthOS Architecture — Principal Engineer Design Review

**Reviewer stance:** independent, not involved in the original design. Nothing here is
defended by appeal to "we already decided this." Every finding is tagged by category and
severity, and the review ends with an explicit verdict on the two questions posed directly:
does this architecture actually support 100+ plugins without core changes, and should
GrowthOS be event-driven.

**Severity key:** 🔴 Critical (must fix before implementation) · 🟠 High (fix before Phase 2)
· 🟡 Medium (fix before it costs real money/time) · 🟢 Low (worth doing, not urgent)

**Category key:** [UC] Unnecessary complexity · [MA] Missing abstraction · [OE]
Overengineering · [UE] Underengineering · [MP] Maintenance problem · [SB] Scalability
bottleneck · [SEC] Security · [PD] Poor decision · [MC] Missing capability · [ALT] A
different architecture would be significantly better

---

## Executive summary

The core trust model — the `ContentItem` approval state machine, project-scoped multi-
tenancy, agents as independent packages — is sound and should survive this review largely
intact. That part of the review is short because there isn't much to challenge; it's
correctly scoped to the actual requirement (human-in-the-loop) and correctly deferred
(billing, RLS, multi-user).

The plugin architecture is where this review earns its keep. **As designed, V1 does not
satisfy the 100+ plugin requirement.** Four separate mechanisms each independently require a
core-code or core-schema change to add a plugin: the registry, the `content_item_type`
enum, the frontend connection UI, and the absence of any interface-version contract. Any one
of these breaks the stated goal on its own; together they mean "add a plugin" currently
means touching five different parts of the system, not creating one package.

The agent-communication model (§ADR 0003, "communicate only through the data layer") is
directionally right but incompletely realized — it solved the coupling problem and created a
polling problem, and it has no real story for the WEBHOOK-capable plugins that are already
in the plugin roster. **Yes, GrowthOS should move to event-driven agent communication** — not
because "event-driven" is fashionable, but because the alternative you already chose
(shared-table polling) is a worse version of the same idea, missing the delivery and
reactivity guarantees an explicit event log gives you almost for free on top of
infrastructure you already have (Postgres, Redis, Arq).

Security has one real gap worth calling 🔴: a single static symmetric key protecting
every plugin credential for every project, with no rotation story. Observability is thinner
than the rest of the design — logging is well thought through, but there is no metrics or
tracing story at all, which matters specifically because a 100+-plugin system's dominant
failure mode is "one of my forty connected plugins is silently degraded," a question logs
alone answer badly.

Nothing below recommends adding infrastructure GrowthOS doesn't need at its actual scale. Where
V1 underbuilt, the fix is a schema/interface change, not a new distributed system.

---

## 1. Plugin architecture — does it actually support 100+ plugins?

**Verdict: No, not as designed.** Four independent failures, each sufficient on its own:

### 1.1 🔴 [PD][ALT] The registry requires a core-code edit per plugin

`docs/plugins/PLUGIN_ARCHITECTURE.md` and `CONTRIBUTING.md` both describe adding a plugin as
"register it in the plugin registry" — a line added to a central file every core contributor
must touch. This is the single most direct violation of "adding a plugin should require
creating a package and configuration, without changing existing core code." At 3 plugins this
is a rounding error. At 100+, it's a file that every plugin author has a merge conflict on,
and a real (if soft) gate on who can add a plugin at all, since it requires a PR against core.

**Fix:** plugin discovery via Python entry points (`pyproject.toml`
`[project.entry-points."growthos.plugins"]`) or a manifest file each plugin package ships
(`plugins/<name>/manifest.json` declaring key, capabilities, content types, config schema).
The registry becomes a *scanner*, not a *list* — it enumerates installed plugin packages at
process startup and builds the catalog from their manifests. Adding a plugin becomes: drop a
package in `plugins/`, install it, restart. Zero lines changed in core. See Architecture V2
§Plugin Discovery and ADR 0007.

### 1.2 🔴 [PD][MP] `content_item_type` is a closed Postgres enum

`database/schema.sql` defines `content_item_type` as a native Postgres `ENUM` with six fixed
values (`reddit_reply`, `linkedin_message`, ...). Every new plugin that can publish something
shaped differently than the existing six — a Discord thread reply, a GitHub issue comment, a
Slack message, a forum post on plugin #47 — requires an `ALTER TYPE ... ADD VALUE` migration
against the core schema. This is the database literally encoding a closed-world assumption
into a table whose entire purpose is to support an open-world, plugin-extensible domain.
This is not a hypothetical scaling concern — it will trigger on the *second* plugin
(WebmasterWorld doesn't cleanly fit `reddit_reply`), let alone the hundredth.

**Fix:** `content_items.type` becomes `text`, validated at the application layer against the
set of content types the currently-installed plugins declare in their manifests (§1.1), not
against a fixed database enum. Native Postgres enums are the wrong tool anywhere a plugin
package — not core schema — owns the set of valid values. See ADR 0008.

### 1.3 🔴 [MA][MC] No plugin-declared config schema — the frontend can't be generic

Nothing in the current design lets a plugin declare *what configuration it needs* in a way
the frontend can consume. `plugin_connections` has credentials and enabled capabilities, but
no `config jsonb` column, and no mechanism analogous to `agents/<name>/config.py`'s pydantic
schema that the dashboard could introspect to render a connection form. Concretely: today,
"connect Reddit" and "connect a 47th plugin" both require someone to hand-write a bespoke
React form in `frontend/`, because there's no generic way to ask a plugin "what fields do you
need, and what are their types." **This means the plugin architecture, exactly as designed,
requires a core (frontend) code change per plugin even if §1.1 and §1.2 are fixed** — it was
solving for backend extensibility only, while the stated requirement doesn't carve out an
exception for the frontend.

**Fix:** every plugin manifest includes a JSON Schema for its connection config (subreddit
allowlist, OAuth scopes, channel IDs — whatever it needs), served by a
`GET /api/v1/plugins/catalog` endpoint, rendered by one generic schema-driven form component
in the frontend (`components/plugin-connection/DynamicConnectionForm.tsx`). One form
component serves all 100+ plugins. See ADR 0009.

### 1.4 🟠 [MC][MP] No plugin interface version contract

`BasePlugin` is a single Protocol with no version. If the interface ever needs a breaking
change (a new required method, a changed `PluginResult` shape) — and over a 100+-plugin,
multi-year lifetime it will — there is no way to know which of the installed plugins were
written against which version of the contract, and no compatibility story for "old plugin,
new core." This is fine for the first 5 first-party plugins you write yourself in the same
PR cycle as the interface; it's a real maintenance liability the moment plugins outlive a
single contributor's working memory of every one of them.

**Fix:** plugins declare `interface_version` in their manifest; the core registry rejects (at
startup, loudly, not at first use) any plugin whose declared version isn't in the range the
running core supports, and `docs/plugins/PLUGIN_ARCHITECTURE.md` gets a stated deprecation
policy (how long an old interface version stays supported after a new one ships).

### 1.5 🟠 [MA][PD] `BasePlugin` is one fat interface across heterogeneous capabilities

`search()` is asked to serve Reddit (free-text discussion search), Google Analytics
(parameterized metrics queries — the plugin's own `README.md` admits this is an awkward fit),
and a future CRM plugin (contact directory lookups) through one method signature
(`PluginQuery -> list[PluginResult]`). This is already visibly straining at 12 plugins — two
of the twelve READMEs contain a version of "this doesn't really fit the interface, document
the real mapping later." At 100+, plugins covering directories, metrics dashboards, ticketing
systems, and messaging platforms will not converge on one shape without the interface either
growing a pile of increasingly-optional fields (interface bloat) or every plugin lying about
what its `PluginResult` fields mean (silent semantic drift).

**Fix:** split `BasePlugin` into capability-specific Protocols agents actually type-check
against — `Searchable`, `Publishable`, `WebhookReceivable`, and a new `MetricsQueryable` for
analytics-shaped plugins (Google Analytics, Search Console) rather than forcing them through
`search()`. A plugin implements the mixins that apply to it; nothing implements a method that
doesn't make sense for it. This also fixes a real type-safety gap: today, whether a plugin
"supports READ" is an enum value checked at runtime by the registry, not something `mypy` can
verify — calling `.search()` on a plugin instance is always type-valid even when the plugin
doesn't really support it well. Segmented Protocols make the type checker enforce what the
capability enum currently only enforces at runtime. See ADR 0007.

### 1.6 🟡 [MP] Plugin-specific config lives in the wrong package

`agents/conversation_finder/README.md`'s example config includes `"platforms":
["reddit","gsc_community"]` and `"search_terms": [...]` — but subreddit allowlists are
Reddit-specific, not Conversation-Finder-specific. Today, every agent that touches Reddit
would need to independently know and duplicate Reddit-shaped config. Once §1.3's plugin
`config jsonb` exists, plugin-specific configuration (subreddit list, channel IDs, OAuth
scopes) belongs on the `plugin_connections` row, and agent config should reference *which*
plugins/capabilities it uses, not re-specify their internals.

---

## 2. Agent architecture & event architecture — should GrowthOS be event-driven?

**Verdict: Yes**, but not by adding a message broker — by making the event model that's
already implicit in the current design *explicit*, using infrastructure already in the stack.

### 2.1 🟠 [PD][ALT] The current model is polling, not decoupling

ADR 0003 rejected direct agent-to-agent calls in favor of "communicate only through the data
layer." That part is correct. But look at what `content_agent`'s own `README.md` says it
actually does: *"Queries `knowledge_items` for the project: recent, high buying-intent, not
yet linked to a `content_item`."* That query is a hand-rolled, per-agent reimplementation of
"give me things that happened since I last checked that I haven't processed yet" — which is
precisely the problem a change feed or event log exists to solve properly. Every agent that
wants to react to another agent's output has to independently invent its own "what's new"
query, with its own risk of missing rows (if the query's filter logic has a bug) or
reprocessing rows (if the "already linked" check is wrong). This isn't decoupling so much as
it's deferred, duplicated coupling — every consumer still has to know the producer's table
shape and invent its own polling contract against it.

### 2.2 🔴 [MC] Webhook-capable plugins have no real reactivity path

Three plugins in the roster (`email`, `slack`, `discord`) declare `WEBHOOK`. The plugin
architecture doc says a webhook "writes through the service layer... like any agent would" —
but nothing *reacts* to that write. `content_agent` only runs when the orchestrator's cron
sequence or an on-demand trigger fires it. A Slack mention that arrives at 2pm sits inert
until the next scheduled sequence — there is no code path from "webhook received" to
"downstream agent notified now." This isn't a hypothetical edge case; it's the stated purpose
of three already-planned plugins, currently unimplementable as designed without bolting on
exactly the kind of ad hoc "call the next thing directly" logic ADR 0003 was written to
prevent.

### 2.3 🟠 [SB][ALT] Sequencing config doesn't scale past a handful of agents

`agents/orchestrator/README.md`'s sequencing config is a project-level, hand-maintained list
of lists (`[["conversation_finder","competitor_watch"],["content_agent"],...]`). This is a
manually-authored DAG per project. It works fine for 6-9 agents. It does not extend cleanly
to a world where new agents (including, eventually, community- or user-authored ones, if
GrowthOS's agent model follows the same extensibility path as its plugin model) need to
express "run me after knowledge is discovered" without every project owner hand-editing a
sequencing list to slot them in correctly.

### 2.4 Recommendation: a lightweight domain-event model, not a message broker

Add a `domain_events` table (Postgres, append-only, the durable source of truth — this is a
transactional outbox: written in the same transaction as the row that caused it, so an event
is never lost to a "commit succeeded, publish failed" race) and dispatch fan-out through Arq
(already in the stack, already async, already Redis-backed — no new infrastructure). Agents
declare event subscriptions in their own package (`agents/content_agent/subscriptions.py`:
"I run on `knowledge_item.created` where `buying_intent >= medium`"), not in a central
per-project sequencing list. The orchestrator's job shrinks to what it's actually good at:
time-based scheduling (cron-triggered discovery runs) and Daily Brief assembly — itself
triggerable by an event (`project.daily_cycle.completed`) instead of a timeout guess.

This is explicitly **not** a recommendation to adopt Kafka, NATS, or a dedicated event-
streaming platform. At GrowthOS's actual scale (one operator, later a handful of projects),
that would be [OE] overengineering of exactly the kind this review is supposed to catch in
the other direction. Postgres-as-outbox plus Arq-as-dispatcher gets the real benefits
(decoupled subscription instead of hand-rolled polling, real-time webhook reactivity, no new
ops burden) without a new distributed system to operate. See Architecture V2 §Event
Architecture and ADR 0006, which supersedes ADR 0003 (the "no direct calls" conclusion
survives; the "how agents discover work" mechanism changes).

---

## 3. Database design

### 3.1 See §1.2 — `content_item_type` as a native enum. 🔴, already covered.

### 3.2 🟡 [SEC][PD] No optimistic concurrency guard on the approval transition

`docs/api/API_DESIGN.md` says the approve/reject endpoints return `409` if the item "is not
currently `pending_review`" but the described check-then-write is a classic TOCTOU race: two
concurrent approve requests (a double-click, or a legitimate retry racing the original) can
both read `pending_review` before either writes. The fix is cheap — `SELECT ... FOR UPDATE`
inside `ContentApprovalService`'s transition, or a `version` integer column with a
compare-and-swap update — but it's currently undocumented, and this is exactly the state
machine the whole system's trust model depends on (`ARCHITECTURE.md` §8 as of the current,
post-freeze section numbering — §5 at the time this finding was written), so "probably fine
in practice" isn't a good enough bar for it. **Closed** — see `ARCHITECTURE.md` §8's
`version`-column concurrency guard and `database/schema.sql`'s `content_items.version`.

### 3.3 🟢 [MC] No plugin catalog table

Related to §1.1/§1.3: once plugins are self-describing (manifest with capabilities, content
types, config schema), it's worth mirroring that catalog into a `plugin_catalog` table
(refreshed at startup from the manifests) so the API/frontend can query "what plugins exist"
without importing Python plugin code into a request path. Low urgency, but worth doing
alongside the manifest work rather than bolted on later.

### 3.4 🟢 [PD] `organization_id` is join-only, everywhere

`docs/database/SCHEMA.md` deliberately avoids duplicating `organization_id` onto every
project-scoped table, for normalization reasons. That's defensible, but it means every
authorization check (`docs/auth/AUTHENTICATION.md`'s `require_project_access`) pays a join. At
v1's scale this is noise. Worth a note-to-self, not a change: if `require_project_access`
ever shows up in a profiler, a denormalized `org_id` on hot-path tables is the fix, and it's
cheap to add later precisely because nothing else depends on its absence.

### 3.5 🟢 [OE→ affirmed, not a finding] `buying_intent` as a 4-value enum

Considered flagging this as premature closed-world modeling like §1.2 — but this one is
different: `buying_intent` is a core, cross-plugin concept assigned by GrowthOS's own agents,
not something plugins define new values for. A closed enum here is the right level of
rigidity. No change recommended; noted so it's clear this was actually checked, not skipped.

---

## 4. API design

### 4.1 🟡 [MC] No plugin catalog endpoint

Follows directly from §1.3 — `GET /api/v1/plugins/catalog` doesn't exist yet in
`docs/api/API_DESIGN.md` and needs to, as the mechanism the frontend uses to render dynamic
connection forms.

### 4.2 🟢 [MC] No API-level rate limiting mentioned

`docs/plugins/PLUGIN_ARCHITECTURE.md` covers rate-limiting *outbound* calls to external
plugin APIs thoroughly. Nothing covers *inbound* rate limiting on GrowthOS's own API — worth
a basic per-session limit, mainly as brute-force/abuse defense on the auth endpoints (ties to
§6.1).

### 4.3 🟢 [PD] Hand-maintained frontend types

`frontend/README.md` describes `lib/types.ts` as manually mirroring backend schemas. FastAPI
generates an OpenAPI schema for free; generating the TypeScript client/types from it
(`openapi-typescript` or similar) removes a manual sync point that will drift, especially as
the API surface grows with the plugin catalog endpoint. Not urgent, cheap to fix, flagged so
it's decided deliberately rather than by default.

---

## 5. Auth & security

### 5.1 🔴 [SEC] Single static key protects every plugin credential, no rotation story

`docs/security/SECURITY.md` and `docs/config/CONFIGURATION.md` both describe
`CREDENTIAL_ENCRYPTION_KEY` as one symmetric key in `.env`, used directly to encrypt every
`plugin_connections.credentials_encrypted` row across every project. This is the single
highest-value secret in the entire system — it decrypts every Reddit/LinkedIn/email/CRM
credential GrowthOS holds — and it's a bare env var with no described rotation mechanism.
Rotating it today means re-encrypting every credential in one operation with no described
migration path, which in practice means it never gets rotated. For a system explicitly
designed to hold credentials capable of posting publicly under the founder's identity, this
is underbuilt relative to the blast radius of it leaking.

**Fix:** envelope encryption — a KMS-held (or, pre-KMS, a locally-held but *rotatable* master
key) wraps per-connection data keys; each `plugin_connections` row is encrypted with its own
data key, itself encrypted by the current master key. Rotating the master key means
re-wrapping data keys (cheap, fast), not re-encrypting every credential from scratch. See ADR
0010. This does not require adopting a cloud KMS on day one — the pattern (envelope
encryption with a rotatable master key) is worth implementing even with a locally-managed
master key, precisely so a future move to AWS/GCP KMS is a key-storage change, not an
encryption-scheme rewrite.

### 5.2 🟡 [MC] No brute-force protection on login

`docs/auth/AUTHENTICATION.md` specifies Argon2id password hashing (good) but nothing about
login attempt rate limiting or lockout. Given a compromised session is a path to every
connected plugin's credentials, this deserves more than "good password hashing."

### 5.3 🟡 [MC] No generic security audit log

`content_items` tracks who approved what — good, and correctly identified in the original
design as load-bearing. But there's no equivalent trail for security-relevant account
actions: login, plugin connect/disconnect, credential rotation, settings changes. Worth a
small `audit_log` table (`actor_user_id`, `action`, `target`, `metadata`, `created_at`)
separate from the approval trail, since these serve different purposes (one is "prove a
human approved this content," the other is "reconstruct what happened during a security
incident").

### 5.4 🟢 [MP][SEC] No plugin trust/sandboxing model, and it will matter at 100+ plugins

Plugins are arbitrary Python code with full process access — able to read env vars (including
`CREDENTIAL_ENCRYPTION_KEY` itself), other plugins' decrypted credentials if they happen to be
in memory during concurrent execution, and make arbitrary outbound network calls. This is a
reasonable trust model for a handful of first-party, code-reviewed plugins. It stops being
reasonable framing well before 100+ plugins if any of them are ever written by anyone other
than you personally. This review isn't recommending you build a plugin sandbox now — that
would be solving a problem you don't have yet — but `docs/plugins/PLUGIN_ARCHITECTURE.md`
should say explicitly that the current trust model assumes all plugins are first-party,
reviewed code, and that a real isolation boundary (subprocess execution, restricted
capabilities) is a prerequisite *before* accepting any plugin GrowthOS's maintainer didn't
personally write or review line-by-line. Stating the boundary explicitly now is cheap; hitting
it silently later is not.

---

## 6. Deployment & scalability

### 6.1 🟢 [SB] Redis is cache, Arq broker, and rate-limit store, all in one instance

Reasonable at v1 scale; worth a monitoring note (which of the three uses is contending) before
it becomes a debugging mystery. Once the event-dispatch mechanism (§2.4) also rides on Arq,
this instance is doing even more — still fine at solo-operator scale, but the first thing to
split (dedicated Redis for event dispatch vs. cache/rate-limiting) if latency ever gets
noisy.

### 6.2 🟢 [SB] Scheduler polls `agent_configs` every minute with no index hint

`docs/jobs/BACKGROUND_JOBS.md`'s scheduler design is fine functionally but doesn't specify an
index or a `next_run_at` computed/materialized column, so the poll query's cost grows
linearly with total `agent_configs` rows across all projects rather than just the due ones.
Trivial to fix, not urgent at current scale, worth doing before Phase 3's second project
doubles the row count for free.

### 6.3 No findings on Docker Compose vs. Kubernetes.

The original justification (`docs/decisions/`, `docs/deployment/DEPLOYMENT.md`) holds up:
Compose is correct for this workload's actual shape, and the "each service is already a
standalone Dockerfile with externalized config" property genuinely does make a later
Kubernetes migration additive rather than a rewrite. Nothing to challenge here — flagged as
checked, not skipped.

---

## 7. Testing, observability, logging

### 7.1 🟠 [MC] No metrics or tracing story at all

`docs/testing/TESTING.md`, `docs/logging/LOGGING.md`, and `docs/deployment/DEPLOYMENT.md`
cover structured logs and error tracking (Sentry) but nothing about metrics (success rate,
latency, throughput per plugin/agent) or distributed tracing. This is a gap specifically
*because* of the 100+ plugin requirement: the dominant operational question in that world is
"which of my N connected plugins is degraded right now," and logs — even good structured
ones — are a poor tool for answering an aggregate question like that. You'd be grepping JSON
lines to reconstruct a number a five-line Prometheus query gives you directly.

**Fix:** OpenTelemetry instrumentation on agent runs and plugin calls (span per `search()`/
`publish()` call, tagged `plugin_key`, `project_id`), exported to a metrics backend
(Prometheus + Grafana self-hosted alongside the existing Compose stack fits the "no new
category of infrastructure" constraint; a hosted alternative like Grafana Cloud's free tier
is a reasonable v1 substitute if self-hosting another service is unwelcome). This is real
scope, not a one-liner — treat it as its own Phase 1/2 workstream, not an afterthought bolted
onto the logging doc.

### 7.2 🟡 [MC] No plugin-interface compatibility testing at scale

Related to §1.4 — even with an interface version declared, there's no CI mechanism described
that verifies *all currently-installed* plugins still pass the shared contract test suite as
the core interface evolves. At 12 plugins this is "run the suite, it's fast." At 100+, either
the suite needs to run selectively/matrixed in CI, or there needs to be a documented policy
for which plugins are tested on every core change versus tested on a slower cadence. Not
urgent today; will be a real CI cost problem within a couple dozen plugins, so worth deciding
the policy before it's actually painful.

---

## 8. Configuration & documentation

Already substantially covered by §1.3 (plugin config schema) and §1.1 (plugin manifest as the
source of catalog data). One additional note:

### 8.1 🟢 [MP] `CONTRIBUTING.md`'s "Adding a new plugin" checklist is now wrong

It currently says "register the plugin in the plugin registry" as step 3 — this directly
contradicts the fix in §1.1 and needs to be rewritten once auto-discovery lands, or new
contributors will keep doing it the old, core-code-touching way out of habit.

---

## 9. What's right and should not change

A review that only lists problems is as misleading as one that only defends. These decisions
were checked adversarially and held up:

- **The `ContentItem` approval state machine as a database-enforced state machine**
  (`ARCHITECTURE.md` §5). This is the actual product. Nothing in this review touches it beyond
  the concurrency-guard note in §3.2.
- **Tenant-ready, solo-first schema** (ADR 0001). Cheap now, and nothing about the plugin or
  event-architecture changes in this review invalidates the `project_id` scoping model — if
  anything, the event log (§2.4) is easier to reason about *because* every event carries a
  `project_id`.
- **Arq over Celery** (ADR 0002). Still correct, and turns out to double as the event
  dispatch mechanism in §2.4 rather than needing reconsideration.
- **Claude primary / OpenAI secondary behind one interface** (ADR 0004). Untouched by this
  review; no findings.
- **Docker Compose over Kubernetes.** See §6.3.
- **Agents as independent packages that never call each other directly** (the actual thesis
  of ADR 0003, as opposed to its polling-based implementation, which §2 revises).

---

## 10. Summary table

| # | Finding | Severity | Categories |
|---|---|---|---|
| 1.1 | Registry requires core-code edit per plugin | 🔴 | PD, ALT |
| 1.2 | `content_item_type` is a closed DB enum | 🔴 | PD, MP |
| 1.3 | No plugin config schema → frontend can't be generic | 🔴 | MA, MC |
| 1.4 | No plugin interface version contract | 🟠 | MC, MP |
| 1.5 | `BasePlugin` is one fat interface | 🟠 | MA, PD |
| 1.6 | Plugin-specific config lives in agent config | 🟡 | MP |
| 2.1 | Agent "communication" is hand-rolled polling | 🟠 | PD, ALT |
| 2.2 | Webhook plugins have no reactivity path | 🔴 | MC |
| 2.3 | Sequencing config doesn't scale past ~10 agents | 🟠 | SB, ALT |
| 3.2 | No concurrency guard on approval transition | 🟡 | SEC, PD |
| 5.1 | Single static credential-encryption key, no rotation | 🔴 | SEC |
| 5.2 | No brute-force protection on login | 🟡 | MC |
| 5.3 | No generic security audit log | 🟡 | MC |
| 5.4 | No plugin trust/sandboxing model stated | 🟢 | MP, SEC |
| 7.1 | No metrics/tracing story | 🟠 | MC |
| 7.2 | No plugin-compat testing-at-scale policy | 🟡 | MC |

**Update, post-freeze:** every 🔴 and 🟠 item above was remediated and merged into the
canonical `ARCHITECTURE.md` (see `ARCHITECTURE_FREEZE.md` at the repo root). The original
proposal and its execution plan are preserved for historical record at
[`docs/architecture/archive/ARCHITECTURE_V2_PROPOSAL.md`](../architecture/archive/ARCHITECTURE_V2_PROPOSAL.md)
and
[`docs/architecture/archive/MIGRATION_V1_TO_V2.md`](../architecture/archive/MIGRATION_V1_TO_V2.md);
the current locked/flexible decision set is
[`docs/architecture/LOCKED_DECISIONS.md`](../architecture/LOCKED_DECISIONS.md).
