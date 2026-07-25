> **ARCHIVED — Status: Executed, 2026-07-25.** This migration plan has been carried out —
> every document it lists as needing an update has been updated, and the canonical
> `ARCHITECTURE.md`, `docs/plugins/PLUGIN_ARCHITECTURE.md`, `docs/agents/AGENT_ARCHITECTURE.md`,
> `database/schema.sql`, and related docs now reflect the target state this plan describes.
> Preserved as the historical record of how the V1→V2 transition was sequenced — useful as a
> template for a future migration, not as a current to-do list. See
> [`ARCHITECTURE_FREEZE.md`](../../../ARCHITECTURE_FREEZE.md) for the resulting frozen state.

# Migration Plan: V1 → V2

## The good news first

No code and no production data exist yet — Phase 0 was documentation only
(`ROADMAP.md`). That means this is not a live-system migration with backfills and
downtime windows; it's a **build-order correction**. The expensive form of this migration —
the one with a backfill script and a maintenance window — is exactly what gets avoided by
doing this review before Phase 1 implementation starts instead of after. This document is
still written as a real migration plan, because pretending V1 was never "live" in your head
(and in `ROADMAP.md`, which explicitly named Reddit as the first plugin) would understate
what's actually changing.

## What triggers this document existing at all

`ROADMAP.md` currently describes Phase 1 in V1 terms: build the registry, build
`content_item_type` as an enum, sequence two agents through orchestrator config. If
implementation started today against that plan, every one of DESIGN_REVIEW's 🔴 findings
would be built first and reworked later — the worst order. This plan reorders Phase 1 so V2's
foundations are built once, correctly, and the Reddit vertical slice still ships as the Phase
1 exit criterion, on top of them.

## Sequencing

### Step 0 — Approve this review

Nothing below starts until `ARCHITECTURE_V2.md` and
[`LOCKED_DECISIONS.md`](../LOCKED_DECISIONS.md) are signed off. This is the actual "freeze"
you asked for — the point past which these decisions stop being open questions.

### Step 1 — Schema foundation (before any application code)

Write `database/schema.sql` directly in its V2 shape — there is no V1 schema running
anywhere to migrate away from, so this is additions/edits to the design file, not an
`ALTER TABLE` sequence against live data:

- `content_items.type` becomes `text` (drop the `content_item_type` enum entirely — it was
  never deployed, so there's no `ALTER TYPE` step, just don't create it).
- Add `plugin_catalog` table.
- Add `config jsonb` to `plugin_connections`.
- Add `domain_events` table with the partial index on undispatched rows.
- Update `docs/database/SCHEMA.md` and `docs/database/ERD.md` to match.

**Exit check:** `database/schema.sql` matches `ARCHITECTURE_V2.md` §3–4 exactly; ERD
regenerated.

### Step 2 — Plugin core: manifest, catalog, segmented Protocols

Before writing the Reddit plugin itself, build the mechanism it will register through:

1. `plugins/_shared/base.py` — the four segmented Protocols (`Searchable`, `Publishable`,
   `WebhookReceivable`, `MetricsQueryable`) replacing the single `BasePlugin`.
2. `plugins/_shared/manifest.py` — `PluginManifest`, `ContentTypeSpec` dataclasses.
3. `backend/app/core/plugin_catalog.py` — the entry-point scanner that builds
   `PluginCatalog` from installed packages at startup and refreshes the `plugin_catalog`
   table.
4. `backend/app/services/plugin_connection.py` — validates connection `config` against the
   target plugin's `config_schema` on write.

**Exit check:** a trivial "hello world" plugin package with a manifest and no real API calls
can be installed, discovered at startup, and shows up via `GET /api/v1/plugins/catalog` —
before Reddit-specific code exists at all. This proves the extensibility mechanism works
independent of any one plugin's complexity.

### Step 3 — Event core: outbox table, publisher, dispatcher

1. `backend/app/core/events.py` — `EventPublisher` used inside service-layer transactions
   (e.g. `KnowledgeBaseService.create_item()` writes the row and its `knowledge_item.created`
   event in the same transaction).
2. Arq periodic job — the dispatcher reading undispatched `domain_events` rows and enqueuing
   per-subscriber jobs.
3. `agents/_shared/subscriptions.py` — the `EventSubscription` declaration mechanism agents
   use.

**Exit check:** publish a test event, confirm a subscribed test handler receives it within
one dispatcher cycle, confirm `dispatched_at` gets set, confirm an event survives a
simulated dispatcher crash mid-cycle (undispatched rows are just re-picked-up — no event
lost).

### Step 4 — Reddit plugin (against the V2 mechanism, not V1's)

Implement `plugins/reddit/` per `plugins/reddit/README.md`, now:
- Declaring a manifest (`content_types=[reddit_reply]`, `config_schema` with subreddit
  allowlist) instead of being hand-registered.
- Implementing `Searchable` + `Publishable` instead of the old single `BasePlugin`.

This step is smaller than it would have been under V1, because steps 2–3 already did the
hard, reusable part.

### Step 5 — Conversation Finder + Content Agent (event-subscribed, not sequenced)

- `agents/conversation_finder`: still cron-triggered (nothing upstream to react to — it
  originates discovery) — via the orchestrator's now-narrower scheduling role.
- `agents/content_agent`: subscribes to `knowledge_item.created` (filtered by
  `buying_intent`) instead of being placed in a hand-authored sequencing list. This is a
  smaller, more testable unit than V1's orchestrator-sequencing approach — a subscription
  filter versus a per-project ordered list.

### Step 6 — Approval Inbox + publish worker

Unchanged from V1's plan — this part of the design had no findings against it. Implement
`ContentApprovalService` with the concurrency guard from DESIGN_REVIEW §3.2
(`SELECT ... FOR UPDATE` or a version column) included from the start, not retrofitted.

### Step 7 — Credential encryption

Implement envelope encryption (`ARCHITECTURE_V2.md` §5) as part of the plugin connection
flow built in Step 2/4 — this is cheaper to build correctly the first time than to retrofit
once real Reddit OAuth tokens are already stored under a flat key.

### Step 8 — Observability

OpenTelemetry spans on the plugin capability calls and agent runs built in Steps 2–5, wired
to Prometheus/Grafana per `ARCHITECTURE_V2.md` §6. This can trail Steps 1–7 by a little (it's
additive instrumentation, not a dependency of the functional path) but should land within
Phase 1, not deferred to "later" indefinitely — DESIGN_REVIEW flagged it 🟠, not 🟢, precisely
because "later" is where observability work goes to die.

## Documents to update once this plan is approved

| Document | Change |
|---|---|
| `ARCHITECTURE.md` | Merge in `ARCHITECTURE_V2.md`'s content as the new canonical description; archive nothing — there's no V1 to preserve as history since it never shipped. |
| `docs/plugins/PLUGIN_ARCHITECTURE.md` | Rewrite around manifests/segmented Protocols; add the explicit trust-model statement from DESIGN_REVIEW §5.4. |
| `docs/agents/AGENT_ARCHITECTURE.md` | Replace the sequencing-config description with `EventSubscription`; narrow the orchestrator's documented responsibilities. |
| `database/schema.sql`, `docs/database/SCHEMA.md`, `docs/database/ERD.md` | Apply Step 1. |
| `docs/api/API_DESIGN.md` | Add `/plugins/catalog`; note the concurrency guard on `/approve`. |
| `docs/security/SECURITY.md` | Replace the flat-key description with envelope encryption; add the rotation runbook. |
| `CONTRIBUTING.md` | Rewrite "Adding a new plugin" checklist — no more registry-line step. |
| `docs/decisions/0003-agent-orchestration.md` | Mark `Status: Superseded by 0006` — keep the file; supersession is itself a record. |
| `ROADMAP.md` | Phase 1 scope updated to this document's Step ordering. |
| `plugins/reddit/README.md`, `agents/conversation_finder/README.md`, `agents/content_agent/README.md` | Update to reference manifests/subscriptions instead of the old registry/sequencing config. |

## If this were a real live-system migration instead

For completeness, since a future V2→V3 migration *will* be a live-system migration: the
pattern this plan would follow is expand/contract — add new nullable columns and new tables
alongside the old ones, dual-write during a transition window, backfill, then drop the old
columns/tables once nothing reads them. `content_item_type`'s enum-to-text change in
particular would, on a live system, need the enum kept temporarily with a `CHECK` constraint
mirroring it during transition, not a direct `ALTER COLUMN TYPE` against production data.
Noted here as the playbook for next time, not needed for this one.
