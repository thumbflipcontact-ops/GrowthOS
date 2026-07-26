# GrowthOS Architecture

This document is the single source of truth for how GrowthOS is built. It is a living
document — when an architectural decision changes, update this file and add an ADR under
`docs/decisions/`.

**Version 2 — frozen 2026-07-25.** This is the second and current version of this document,
produced by a Principal Engineer design review of the original design
(`docs/reviews/DESIGN_REVIEW.md`) and approved before any implementation began. There is no
V1 document to consult — the review happened before anything was built, so this file was
updated in place rather than left to drift from a shipped V1. See
[`ARCHITECTURE_FREEZE.md`](ARCHITECTURE_FREEZE.md) at the repo root for the freeze summary and
[`docs/architecture/LOCKED_DECISIONS.md`](docs/architecture/LOCKED_DECISIONS.md) for the full
locked/flexible decision inventory.

## 1. What GrowthOS is

GrowthOS is an operating system for a solo founder running one or more SaaS businesses. It
researches, drafts, and prioritizes; a human always publishes. Every product GrowthOS
manages — ScoutSEO today, others later — is a **Project**, not a fork of the codebase.
Nothing in `backend/`, `agents/`, or `plugins/` may contain product-specific logic. If you
find yourself writing `if project.slug == "scoutseo"`, the abstraction is wrong — the
difference belongs in project configuration, not code.

GrowthOS is also, from day one, a platform meant to support a large and growing number of
integrations — **100+ plugins over its lifetime, each addable by creating a plugin package
and configuration, with zero changes to core code.** This constraint shapes §5–7 below more
than any other single requirement in the system, and it is the reason this document has a
"Version 2": the original plugin design didn't actually meet it, four different ways (see
`docs/reviews/DESIGN_REVIEW.md` §1). Every plugin- and agent-facing section below is written
to satisfy this constraint mechanically, not by convention or discipline.

## 2. Guiding constraints

These are load-bearing. Every design decision below exists to satisfy them.

1. **Human-in-the-loop is architecturally enforced, not a UI convention.** No code path
   exists that lets an agent publish externally-visible content without a human approval
   transition recorded against a specific user. See §8.
2. **Multi-project, tenant-ready, solo-first.** Every domain table is scoped by
   `organization_id` and `project_id` from day one. GrowthOS v1 ships with exactly one
   organization (yours) and no signup flow — but the schema, auth, and API never assume
   single-tenancy, so opening GrowthOS to other founders later is a feature flag and a
   billing integration, not a migration project. See `docs/decisions/0001-multi-tenancy.md`.
3. **Agents are independent and swappable, and they never call each other.** Each agent is a
   self-contained package with its own config schema, prompts, tools, memory scope, and
   tests. Agents communicate only by publishing and subscribing to **domain events** over the
   shared data layer — never through direct function calls, shared in-memory state, or a
   central per-project sequencing list. You can delete an agent's package and nothing else
   breaks. See §7.
4. **Plugins are self-describing adapters, discovered automatically, behind segmented
   capability contracts.** A plugin declares what it is — its capabilities, the content types
   it can publish, its configuration schema — in a manifest the core system discovers at
   startup. Core code never hand-lists which plugins exist, never imports a specific plugin
   module, and never encodes a plugin-specific concept (a content type, a config field) into
   a fixed schema. Adding a plugin is: create the package, install it, restart. See §5–6.
5. **Everything discovered becomes structured knowledge.** No agent is allowed to produce an
   ephemeral result that only lives in a log line or a Slack message. If a Conversation
   Finder run reads 40 Reddit threads and 3 are relevant, all 3 become `knowledge_items` rows
   — queryable a year later, and each one publishes a `knowledge_item.created` domain event
   any interested agent can react to.

## 3. System layers

```
┌─────────────────────────────────────────────────────────────────┐
│ Frontend (Next.js)                                               │
│  Morning Brief · Approval Inbox · Knowledge Base Explorer ·      │
│  Project Settings · Dynamic Plugin Connection Forms (§6)         │
└───────────────────────────────┬───────────────────────────────────┘
                                 │ REST (JSON) — see docs/api/API_DESIGN.md
┌───────────────────────────────▼───────────────────────────────────┐
│ API layer (FastAPI)                                               │
│  AuthN/Z · request validation · project scoping · webhook ingress │
│  · plugin catalog                                                 │
└───────────────────────────────┬───────────────────────────────────┘
                                 │
┌───────────────────────────────▼───────────────────────────────────┐
│ Domain / service layer (backend/app/services)                     │
│  ContentApprovalService · KnowledgeBaseService · AgentRunService · │
│  PluginConnectionService · EventPublisher (transactional outbox)  │
└──────────┬──────────────────────────┬────────────────────────────┘
           │                          │ domain_events (§7)
┌──────────▼───────────────┐   ┌──────▼──────────────────────────────┐
│ Agent layer (agents/)     │   │ Event dispatcher (Arq periodic job)  │
│  each agent: config,      │◄──┤  reads undispatched domain_events,   │
│  prompts, tools, memory,  │   │  enqueues one Arq job per subscriber │
│  and its own              │   └──────────────────────────────────────┘
│  EventSubscriptions (§7)  │
└──────────┬─────────────────┘
           │ PluginRegistry (built from PluginCatalog, §5)
┌──────────▼───────────────────────────────────────────────────────┐
│ Plugin layer (plugins/)                                           │
│  Each plugin: self-describing manifest + whichever of             │
│  Searchable / Publishable / WebhookReceivable / MetricsQueryable   │
│  it actually implements (§5)                                      │
└──────────┬─────────────────────────────────────────────────────┘
┌──────────▼─────────────────────────────────────────────────────┐
│ Data layer                                                        │
│  PostgreSQL + pgvector (system of record, embeddings,             │
│    domain_events outbox, plugin_catalog)                          │
│  Redis (Arq queue — job execution and event dispatch — cache,     │
│    rate limiting)                                                 │
└───────────────────────────────────────────────────────────────────┘
```

## 4. Core domain concepts

| Concept | What it is |
|---|---|
| **Organization** | The tenant boundary. v1 has one row. |
| **Project** | One SaaS business GrowthOS operates for (ScoutSEO, future products). Holds ICP definition, brand voice, plugin connections, agent schedules. |
| **Agent** | A background-runnable unit of capability (Customer Finder, Content Agent, etc.), triggered by a schedule or by subscribed domain events. See `docs/agents/AGENT_ARCHITECTURE.md`. |
| **Plugin** | A self-describing adapter to one external system, discovered via manifest, implementing whichever capability Protocols apply. See `docs/plugins/PLUGIN_ARCHITECTURE.md`. |
| **Domain Event** | An immutable record of something that happened (`knowledge_item.created`, `content_item.approved`, ...), the mechanism agents use to react to each other's output. See §7. |
| **KnowledgeItem** | A structured extraction from one discovered piece of external content. The institutional memory. See `docs/knowledge-base/KNOWLEDGE_BASE.md`. |
| **ContentItem** | Anything an agent drafted for external publication, gated by human approval. See §8. |
| **AgentRun** | One execution of one agent for one project — the audit trail. |
| **DailyBrief** | The materialized "what should I do today" view, assembled by the orchestrator, triggered by a `project.daily_cycle.completed` event. |

## 5. Plugin discovery and capability interfaces

**This section exists to satisfy the 100+ plugin, zero-core-change requirement mechanically.**
See `docs/decisions/0007-plugin-discovery-and-interface-segmentation.md` for the full
reasoning and `docs/plugins/PLUGIN_ARCHITECTURE.md` for the complete plugin developer guide;
this is the summary that belongs in the system-level architecture doc.

### Manifests, not a hand-maintained registry

Every plugin package ships a manifest declaring its identity, capabilities, content types,
and configuration schema:

```python
# plugins/reddit/manifest.py
MANIFEST = PluginManifest(
    key="reddit",
    interface_version="1.0",
    capabilities=["searchable", "publishable"],
    content_types=[ContentTypeSpec(key="reddit_reply", max_length=10_000)],
    config_schema=RedditConnectionConfig,
    auth_type="oauth2",
)
```

At process startup, the core `PluginCatalog` scans installed packages for their manifests via
Python entry points (`[project.entry-points."growthos.plugins"]`) — it is a *scanner*, never
a list requiring a core-code edit. A plugin whose `interface_version` is unsupported by the
running core fails loudly at startup. **Adding a plugin is: create the package, install it,
restart — zero lines changed anywhere else in the system.**

### Segmented capability interfaces

Plugin capabilities are four distinct Protocols, not one interface gated by a runtime enum:

```python
class Searchable(Protocol):
    async def search(self, query: PluginQuery) -> list[PluginResult]: ...

class Publishable(Protocol):
    async def publish(self, item: "ContentItem") -> PublishResult: ...

class WebhookReceivable(Protocol):
    async def handle_webhook(self, payload: dict) -> None: ...

class MetricsQueryable(Protocol):
    """For analytics/reporting-shaped plugins (Google Analytics, Search Console) whose
    data doesn't fit free-text search."""
    async def query_metrics(self, spec: MetricsQuerySpec) -> MetricsResult: ...
```

A plugin implements whichever Protocols describe what it actually does. The
`PluginRegistry.get(key, required_capability)` call performs a structural type check against
the requested Protocol — a plugin that doesn't implement `Publishable` cannot be handed to
code expecting one, enforced by the type system, not just a runtime capability-enum check.
This also means the registry itself never special-cases a specific plugin: it only ever
reasons about which Protocols a given plugin instance satisfies.

### Two independent gates on publishing

A plugin's own declared capability (code-level, fixed at implementation time) is the first
gate. `plugin_connections.capabilities_enabled` (data-level, per-project, user-controlled) is
the second — a project can have valid publish-capable Reddit credentials and still have
publishing disabled for that connection. Both must allow it; neither alone is sufficient.

### Trust model

Plugins are Python code with full process access, executed in-process. The current design
assumes every installed plugin is first-party, code-reviewed code — there is no sandboxing
or capability-restricted execution boundary. **This is a stated limit, not an oversight:** a
real isolation boundary (subprocess execution, restricted capabilities) is a prerequisite
before accepting any plugin not personally written or reviewed by the GrowthOS maintainer.
See `docs/security/SECURITY.md` §Plugin trust model and
`docs/architecture/LOCKED_DECISIONS.md` §2.

## 6. Plugin-contributed content types and configuration

**Closes the two remaining ways V1 silently required a core-code change per plugin** — see
`docs/decisions/0008-plugin-contributed-content-types.md` and
`docs/decisions/0009-plugin-config-schema-dynamic-ui.md`.

`content_items.type` is `text`, validated at the application layer against the union of
content types declared by currently-installed plugin manifests — never a closed database
enum. (`buying_intent`, by contrast, stays a native Postgres enum deliberately: it's a core,
cross-plugin concept GrowthOS's own agents assign, not something a plugin package
contributes new values for. The distinction is: does core own this taxonomy, or does a
plugin? Core-owned → enum is fine. Plugin-contributed → text, app-validated.)

`plugin_connections` carries a `config jsonb` column, validated against the owning plugin's
`config_schema` on write — plugin-specific settings (a subreddit allowlist, OAuth scopes,
monitored channel IDs) live on the connection that needs them, not duplicated into every
agent config that happens to touch that plugin.

The frontend renders **one generic, schema-driven connection form**
(`DynamicConnectionForm`) from whatever `config_schema` a plugin's manifest declares, served
via `GET /api/v1/plugins/catalog`. Adding a plugin requires zero frontend code changes — the
100+ plugin requirement is met on both sides of the stack, not just the backend.

## 7. Event architecture: how agents actually communicate

**Agents never call each other. They publish and subscribe to domain events.** See
`docs/decisions/0006-event-driven-agent-communication.md` for the full reasoning; this is
the mechanism summary.

### The outbox

```sql
create table domain_events (
    id            uuid primary key default gen_random_uuid(),
    project_id    uuid not null references projects(id) on delete cascade,
    event_type    text not null,           -- 'knowledge_item.created', 'content_item.approved', ...
    payload       jsonb not null,
    occurred_at   timestamptz not null default now(),
    dispatched_at timestamptz
);
```

Every domain event is written **in the same database transaction** as the row that causes
it — a transactional outbox. This is what makes the mechanism reliable: an event can never be
lost to a "row committed, publish call failed separately" race.

### Dispatch, not a message broker

A lightweight Arq periodic job reads undispatched `domain_events` rows and enqueues one Arq
job per subscribed handler, reusing infrastructure already in the deployment topology
(Postgres as the durable log, Arq/Redis as the fan-out mechanism — no new broker, no new
service to operate). This is a deliberate rejection of Kafka/NATS/dedicated event-streaming
infrastructure at GrowthOS's actual scale — see `docs/scalability/SCALABILITY.md`.

### Subscriptions replace sequencing

```python
# agents/content_agent/subscriptions.py
SUBSCRIPTIONS = [
    EventSubscription(
        event_type="knowledge_item.created",
        filter=lambda payload: payload["buying_intent"] in ("medium", "high"),
    ),
]
```

Each agent declares what it reacts to, inside its own package. Adding an agent that reacts to
an existing event requires editing nothing else. Webhook-triggered discovery (a Slack mention,
a Discord message) and cron-triggered discovery both write their row and its domain event in
the same transaction and flow through the identical dispatch path — there is no special case
for "real-time" versus "scheduled" discovery.

The **orchestrator**'s role narrows to what's genuinely time-based and has nothing upstream
to react to: cron-triggering agents like `conversation_finder` that originate a discovery
cycle, and assembling the `DailyBrief`, itself triggered by a `project.daily_cycle.completed`
event rather than a timeout heuristic. See `agents/orchestrator/README.md`.

## 8. The approval state machine

This is the mechanism that makes "AI researches and drafts, human publishes" true at the
code level instead of just true in the README. Unchanged by the V2 review except for one
addition (the concurrency guard, noted below) — this was the one area of the original design
checked adversarially and found sound.

```
   draft ──► pending_review ──► approved ──► published
               │                    │
               ▼                    ▼
            rejected            (publish failed → back to approved,
                                  retried by the publish worker)
```

Rules enforced in `ContentApprovalService`, not in the API layer or the UI, so there is
exactly one place this can be gotten wrong:

- Only an agent (via `AgentRunService`) can create a `ContentItem`, and it is always created
  in `draft`, immediately auto-advanced to `pending_review` once the agent's own
  self-check passes (e.g. length limits, banned-phrase filter).
- Only a human user, authenticated, acting through the API, can transition
  `pending_review → approved` or `pending_review → rejected`. This transition always writes
  `reviewed_by_user_id` and `reviewed_at`. There is no code path that sets `approved` without
  both fields populated. **The transition is guarded against concurrent double-approval**
  (`SELECT ... FOR UPDATE` or an optimistic version column) — a gap identified during design
  review and closed before implementation rather than discovered as a race condition later.
- Only the publish worker, and only for a `ContentItem` already in `approved`, may call a
  plugin's `publish()` and transition to `published`. This worker is the *only* caller of any
  plugin's `Publishable.publish()` in the entire codebase.
- A plugin that does not implement `Publishable` cannot be handed to the publish worker at
  all — enforced structurally by the type system (§5), not just by a runtime capability
  check.

**Implemented** (Phase 2C, see `docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md` and
`docs/reviews/PUBLISHING_WORKFLOW_IMPLEMENTATION_REPORT.md`) — `app/services/
content_approval.py` (`ContentApprovalService`), `app/services/content_drafts.py`'s
`submit_for_review` (the self-check + auto-advance step), and `app/jobs/publish.py` (the
real publish worker). The concurrency guard is the optimistic `version` column, not `SELECT
... FOR UPDATE` — a single atomic `UPDATE ... WHERE status IN (...) AND version = :expected`
does both the state-transition check and the concurrency check in one round trip; a
mismatch on either affects zero rows and raises `InvalidStateTransition`, never a silent
double-transition.

**One addition beyond this section's original diagram: `archived`.** A fifth
`content_items.status` value, reachable from `draft` or `pending_review` only (never from
anything already decided or published) — a human choosing "no longer relevant" without
formally rejecting the content itself. Added because Phase 2B's Content Agent produces
`draft` rows that fail the self-check (too long, a banned phrase) with no path back into the
flow above otherwise; without `archived`, such a row would simply sit in `draft` forever
with no way to close it out. This is additive to the diagram, not a change to any rule
listed above it — `pending_review → approved`/`rejected` and `approved → published` are
exactly as specified.

## 9. Credential encryption

Plugin credentials are protected by **envelope encryption**, not a single static key — see
`docs/decisions/0010-envelope-encryption-for-credentials.md`. A master key (operator-held via
the deployment platform's secret store; a cloud KMS is a compatible future upgrade) encrypts
a unique data key per `plugin_connections` row; the data key encrypts the actual credential.
Rotating the master key means re-wrapping stored data keys, not re-encrypting every stored
credential — the operation that makes rotation something that can actually happen. See
`docs/security/SECURITY.md`.

## 10. Observability

Plugin capability calls and agent runs are traced (OpenTelemetry spans tagged `plugin_key` /
`agent_key` / `project_id`) and exported to metrics dashboards — the operationally necessary
counterpart to a system explicitly designed to grow to 100+ independently-failing plugins,
where "which of my plugins is silently degraded" needs to be a query, not a grep. See
`docs/observability/OBSERVABILITY.md` for the full design; this is a first-class Phase 1
workstream, not a documentation-only addition.

## 11. Why not simpler?

A reasonable objection: this is a lot of structure for a v1 with one user. Four things justify
paying for it up front rather than later:

- **The multi-project and multi-tenant scoping is cheap now and expensive later.** Adding
  `organization_id`/`project_id` to every table costs nothing when there's one row of each.
  Retrofitting it after real usage data exists means a painful backfill.
- **The approval state machine is the entire value proposition.** GrowthOS's trust with its
  one user depends on it being *impossible*, not just unlikely, for it to post something
  without sign-off.
- **The 100+ plugin requirement is explicit and stated up front, not aspirational.** Building
  the manifest/discovery/segmented-interface mechanism now, before the second plugin exists,
  costs one implementation pass. Retrofitting it after a dozen plugins already exist means
  rewriting all of them plus the mechanism — this is precisely the trap the design review
  caught before it was built, not after.
- **The event architecture replaces a mechanism (sequencing config) that would have needed
  replacing anyway.** This isn't added complexity relative to V1 — it's the same amount of
  machinery (agents react to something, in some order), built on a primitive (domain events)
  that scales with agent count instead of against it.

Everything else — Analytics Agent, CRM Assistant, multi-user roles, billing, a dedicated event
broker, plugin sandboxing — is deliberately deferred. See `ROADMAP.md` and
`docs/architecture/LOCKED_DECISIONS.md` §2.

## 12. Cross-references

- Freeze summary: [`ARCHITECTURE_FREEZE.md`](ARCHITECTURE_FREEZE.md) (repo root)
- Locked vs. flexible decisions: `docs/architecture/LOCKED_DECISIONS.md`
- Design review that produced this version: `docs/reviews/DESIGN_REVIEW.md`
- Folder structure: `README.md` §Repository layout
- Database schema & ERD: `docs/database/SCHEMA.md`, `docs/database/ERD.md`
- Agent architecture: `docs/agents/AGENT_ARCHITECTURE.md`
- Plugin architecture: `docs/plugins/PLUGIN_ARCHITECTURE.md`
- API design: `docs/api/API_DESIGN.md`
- Auth: `docs/auth/AUTHENTICATION.md`
- Background jobs: `docs/jobs/BACKGROUND_JOBS.md`
- Config / logging / errors: `docs/config/`, `docs/logging/`, `docs/errors/`
- Testing / deployment / security / scalability / observability: `docs/testing/`,
  `docs/deployment/`, `docs/security/`, `docs/scalability/`, `docs/observability/`
- Knowledge base: `docs/knowledge-base/KNOWLEDGE_BASE.md`
- Decision history: `docs/decisions/`
