> **ARCHIVED — 2026-07-25.** This proposal was approved and merged into the canonical
> [`ARCHITECTURE.md`](../../../ARCHITECTURE.md) at the repo root. Preserved here as the
> historical record of the Principal Engineer design review's proposed remediation — do not
> treat this as a current spec; if anything below conflicts with `ARCHITECTURE.md` or the
> `docs/decisions/` ADRs, those are correct and this is not. See
> [`ARCHITECTURE_FREEZE.md`](../../../ARCHITECTURE_FREEZE.md) for the frozen state this
> produced.

# GrowthOS Architecture — Version 2 (Proposed)

**Status:** proposed, pending your sign-off. Nothing in this document is implemented, and
nothing in the canonical `ARCHITECTURE.md` changes until this is approved and
[`MIGRATION_V1_TO_V2.md`](MIGRATION_V1_TO_V2.md) is executed. This document only covers what
changes from V1; everything not mentioned here (the `ContentItem` approval state machine,
project-scoping, the auth model, the tech stack) is unchanged — see `ARCHITECTURE.md` and
`docs/reviews/DESIGN_REVIEW.md` §9 for what was checked and kept.

Every section below exists to close a specific finding in
[`docs/reviews/DESIGN_REVIEW.md`](../reviews/DESIGN_REVIEW.md) — cited inline.

---

## 1. Plugin discovery: manifests, not a registry list

**Closes DESIGN_REVIEW §1.1, §1.4.**

### The manifest

Every plugin package ships a manifest declaring what it is, without requiring core code to
know about it in advance:

```python
# plugins/reddit/manifest.py
from growthos.plugins import PluginManifest, ContentTypeSpec

MANIFEST = PluginManifest(
    key="reddit",
    interface_version="1.0",              # closes §1.4 — core checks this at load time
    capabilities=["searchable", "publishable"],   # see §2 — segmented, not one enum
    content_types=[
        ContentTypeSpec(key="reddit_reply", max_length=10_000, publish_target="thread"),
    ],
    config_schema=RedditConnectionConfig,   # pydantic model → JSON Schema, see §3
    auth_type="oauth2",
)
```

### Discovery

At process startup, the core `PluginCatalog` scans installed packages for a `manifest.py`
exposing `MANIFEST` (via Python entry points declared in each plugin's `pyproject.toml`
under `[project.entry-points."growthos.plugins"]` — the standard extension-point mechanism,
not a bespoke directory-walk). A plugin whose `interface_version` falls outside the range the
running core supports fails loudly at startup with a clear error, not silently at first use.

**Adding a plugin is now:** create `plugins/<name>/` (manifest, client, `plugin.py`
implementing the relevant capability Protocols, tests), install it, restart. **Zero lines
changed in `backend/`, `agents/`, or any other plugin's code.** This is the literal bar the
100+ plugin requirement set, and it's now met mechanically, not by convention.

`docs/plugins/PLUGIN_ARCHITECTURE.md` and `CONTRIBUTING.md`'s "adding a plugin" checklist get
rewritten to match — no more "register it in the registry" step.

---

## 2. Segmented plugin interfaces

**Closes DESIGN_REVIEW §1.5.**

`BasePlugin` as one fat Protocol is replaced by capability-specific Protocols. A plugin
implements whichever apply — `mypy` now actually enforces what the old capability enum only
checked at runtime:

```python
class Searchable(Protocol):
    async def search(self, query: PluginQuery) -> list[PluginResult]: ...

class Publishable(Protocol):
    async def publish(self, item: "ContentItem") -> PublishResult: ...

class WebhookReceivable(Protocol):
    async def handle_webhook(self, payload: dict) -> None: ...

class MetricsQueryable(Protocol):
    """For analytics/reporting-shaped plugins (Google Analytics, Search Console) that
    don't fit free-text search — closes the 'awkward mapping' problem both of those
    plugins' READMEs already flagged under V1."""
    async def query_metrics(self, spec: MetricsQuerySpec) -> MetricsResult: ...

class GrowthOSPlugin(Protocol):
    manifest: PluginManifest
    async def health_check(self) -> bool: ...
```

The registry's `get(key, required_capability)` now does an `isinstance`/Protocol check against
the specific capability Protocol requested, not a membership check against an enum list — a
plugin that doesn't implement `Publishable` structurally can't be handed to code expecting
one, full stop, independent of what its manifest claims.

`google_analytics` and `search_console` (currently forced into an awkward `search()` mapping,
per their own V1 READMEs) implement `MetricsQueryable` instead — their `README.md`'s
"not a natural fit" caveat goes away because the interface now fits what they actually do.

---

## 3. Plugin-contributed content types and config

**Closes DESIGN_REVIEW §1.2, §1.3, §1.6, §3.1, §3.3, §4.1.**

### Schema change

```sql
-- content_items.type: was `content_item_type` enum, now:
alter table content_items alter column type type text;
-- validated at the application layer against the union of content_types declared by
-- currently-installed plugin manifests (§1) — not a fixed database enum. See
-- MIGRATION_V1_TO_V2.md for the actual migration steps and the app-layer validator.

create table plugin_catalog (
    plugin_key          text primary key,
    interface_version   text not null,
    capabilities        text[] not null,
    content_types       jsonb not null,     -- mirrors each plugin's ContentTypeSpec list
    config_schema       jsonb not null,     -- JSON Schema, generated from the plugin's pydantic model
    auth_type           text not null,
    refreshed_at        timestamptz not null default now()
);
```

`plugin_catalog` is refreshed from the in-process manifest scan at startup (§1) — it exists so
the API and frontend can query "what plugins exist and what do they need" without importing
plugin Python code into a request path (closes §3.3).

`plugin_connections` gains a `config jsonb` column — plugin-specific settings (a subreddit
allowlist, OAuth scopes, monitored channel IDs) live on the connection, validated against that
plugin's `config_schema`, not duplicated into every agent that happens to use the plugin
(closes §1.6). `agents/conversation_finder`'s config shrinks to "which plugin connections and
capability filters to use," not platform-specific search parameters.

### API and frontend

```
GET /api/v1/plugins/catalog                     → plugin_catalog rows, incl. config_schema
POST /api/v1/projects/{id}/plugin-connections    → validated against the target plugin's config_schema
```

One frontend component, `DynamicConnectionForm`, renders any plugin's connection form from its
`config_schema` (JSON Schema → form fields is a solved, boring problem — e.g.
`@rjsf/core`-style schema-driven forms). **Adding a plugin now requires zero frontend code
changes**, closing the gap DESIGN_REVIEW §1.3 identified: V1's plugin architecture was
solving backend extensibility only, while the stated requirement had no such carve-out.

---

## 4. Event architecture: domain events, not sequencing config or polling

**Closes DESIGN_REVIEW §2.1, §2.2, §2.3. Supersedes ADR 0003's *mechanism* (its conclusion —
no direct agent-to-agent calls — survives unchanged; see ADR 0006.)**

### The shape

```sql
create table domain_events (
    id            uuid primary key default gen_random_uuid(),
    project_id    uuid not null references projects(id) on delete cascade,
    event_type    text not null,          -- 'knowledge_item.created', 'content_item.approved', ...
    payload       jsonb not null,          -- the event-specific data; always includes the source row id
    occurred_at   timestamptz not null default now(),
    dispatched_at timestamptz              -- null until fan-out has been attempted at least once
);
create index idx_domain_events_undispatched on domain_events (project_id) where dispatched_at is null;
```

`domain_events` is written **in the same database transaction** as the row that causes it —
this is the transactional outbox pattern, and it's the detail that actually matters: it means
an event is never lost to a "the `knowledge_item` insert committed but the event publish call
failed" race, which a naive "write the row, then separately call `publish_event()`" approach
would be exposed to.

### Dispatch

A lightweight dispatcher (an Arq periodic job, sub-second interval — reusing infrastructure
already in the stack, not a new broker) reads undispatched rows from `domain_events` and
enqueues one Arq job per (event, subscriber) pair, then marks `dispatched_at`. This gives
near-real-time delivery (bounded by the dispatcher's poll interval, tunable down to whatever
latency the webhook use case needs) without requiring a dedicated message broker — Postgres is
the durable log, Arq is the fan-out mechanism, both already exist in the deployment topology.

### Subscriptions replace sequencing config

```python
# agents/content_agent/subscriptions.py
SUBSCRIPTIONS = [
    EventSubscription(
        event_type="knowledge_item.created",
        filter=lambda payload: payload["buying_intent"] in ("medium", "high"),
    ),
]
```

Each agent declares what it reacts to, in its own package — adding an agent that reacts to
existing events requires no edit to any other agent's code and no edit to a central
per-project sequencing list (closes §2.3's scaling concern). The orchestrator's
responsibility shrinks to what's genuinely time-based: cron-triggered discovery runs (nothing
upstream to react to — `conversation_finder` has to originate its own cycle) and Daily Brief
assembly, itself now triggered by a `project.daily_cycle.completed` event rather than a
timeout heuristic.

### Webhook plugins now have a real reactivity path

A `WebhookReceivable` plugin's `handle_webhook()` writes its row (e.g. a new `knowledge_item`
from a Slack mention) and its `knowledge_item.created` event in one transaction, exactly like
a scheduled agent run does. `content_agent`'s existing subscription picks it up within one
dispatcher cycle — closing §2.2 without a special case: webhook-triggered and cron-triggered
discovery flow through the identical event path.

### Why not Kafka/NATS/a dedicated event-streaming platform

Explicitly considered and rejected for this scale. GrowthOS's event volume (bounded by one
operator's, later a handful of projects', agent-run and webhook frequency) doesn't approach
where a dedicated streaming platform's operational cost — a new service to run, monitor, and
back up, a new consumer-group/offset model to reason about — pays for itself over
Postgres-as-outbox-plus-Arq. Revisit only if event volume or fan-out breadth grows by orders
of magnitude beyond what a solo-founder-scale system produces — see
`docs/scalability/SCALABILITY.md`, which this document doesn't otherwise revise.

---

## 5. Credential encryption: envelope encryption

**Closes DESIGN_REVIEW §5.1.**

Replace direct encryption under one static `CREDENTIAL_ENCRYPTION_KEY` with envelope
encryption: a master key (initially operator-held, e.g. injected via the deployment
platform's secret store as today — a cloud KMS is a drop-in upgrade, not a redesign) encrypts
a unique **data key** generated per `plugin_connections` row; the data key, not the master
key, encrypts that row's actual credential. The wrapped (encrypted) data key is stored
alongside the ciphertext.

**Rotation** becomes: generate a new master key, re-wrap every stored data key under it (fast
— data keys are small, this touches no actual credential ciphertext), retire the old master
key. This is the operation that was previously undefined and, in practice, would never have
happened. `docs/security/SECURITY.md`'s incident-response runbook gets a concrete "rotate the
master key" procedure instead of a hand-wave.

---

## 6. Observability: metrics and tracing added as a real workstream

**Closes DESIGN_REVIEW §7.1.**

OpenTelemetry spans around every plugin capability call (`search`, `publish`,
`query_metrics`, `handle_webhook`) and every agent run, tagged `plugin_key` / `agent_key` /
`project_id`, exported to Prometheus (self-hosted alongside the existing Compose stack — see
`docs/deployment/DEPLOYMENT.md`, unchanged otherwise) with Grafana dashboards for: per-plugin
success rate and p50/p95 latency, per-agent run duration and outcome distribution, event
dispatch lag (`domain_events` age of oldest undispatched row — the health signal for §4's
whole mechanism). This is scoped as its own implementation workstream in
`docs/roadmap/` /`ROADMAP.md`, not a documentation-only addition — see the migration plan.

---

## 7. What does not change

- The `ContentItem` approval state machine and its enforcement boundary (still the only thing
  that can reach `published`) — untouched, see `ARCHITECTURE.md` §5.
- Project/org scoping model (ADR 0001) — the event log and plugin catalog both slot into it
  cleanly (`domain_events.project_id`, connections still project-scoped).
- Arq over Celery (ADR 0002) — reinforced, now doing double duty as the event dispatcher.
- Claude primary / OpenAI secondary (ADR 0004).
- Docker Compose topology (`docs/deployment/DEPLOYMENT.md`) — the dispatcher is a new Arq
  periodic job, not a new service.
- REST API style and versioning (`docs/api/API_DESIGN.md`) — extended (§3), not replaced.

## 8. Revised system diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ Frontend (Next.js) — incl. generic DynamicConnectionForm (§3)    │
└───────────────────────────────┬───────────────────────────────────┘
┌───────────────────────────────▼───────────────────────────────────┐
│ API layer (FastAPI) — + /plugins/catalog                          │
└───────────────────────────────┬───────────────────────────────────┘
┌───────────────────────────────▼───────────────────────────────────┐
│ Domain / service layer                                            │
│  ContentApprovalService · KnowledgeBaseService · EventPublisher   │
└──────────┬──────────────────────────┬─────────────────────────────┘
           │                          │ domain_events (outbox, §4)
┌──────────▼───────────────┐   ┌──────▼──────────────────────────────┐
│ Agent layer               │   │ Event dispatcher (Arq periodic job) │
│  each agent declares its  │◄──┤  reads undispatched events,         │
│  own EventSubscriptions   │   │  enqueues Arq jobs per subscriber   │
└──────────┬─────────────────┘   └──────────────────────────────────┘
           │ PluginRegistry (built from PluginCatalog, §1)
┌──────────▼───────────────────────────────────────────────────────┐
│ Plugin layer — Searchable / Publishable / WebhookReceivable /     │
│ MetricsQueryable Protocols (§2), each plugin self-describing (§1) │
└──────────┬─────────────────────────────────────────────────────┘
┌──────────▼─────────────────────────────────────────────────────┐
│ Data layer: PostgreSQL (+ domain_events, plugin_catalog) + Redis │
└───────────────────────────────────────────────────────────────┘
```
