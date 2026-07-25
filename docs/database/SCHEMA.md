# Database Schema

Source of truth DDL: [`database/schema.sql`](../../database/schema.sql). This document
explains the *why* behind it; the SQL file is the *what*.

**Version 2** — updated after the Principal Engineer design review
(`docs/reviews/DESIGN_REVIEW.md`) added `plugin_catalog`, `domain_events`, and `audit_log`,
changed `content_items.type` from a native enum to `text`, added `plugin_connections.config`
and its envelope-encryption columns, and added a `version` column to `content_items` for
concurrency control. See `docs/decisions/0006`, `0007`, `0008`, `0009`, `0010`.

## Design principles

**Every tenant-scoped table carries `project_id`, not `organization_id`.** A project belongs
to exactly one org (`projects.org_id`), so `organization_id` is derivable via a join and
deliberately not duplicated onto every downstream table. This is a normalization choice, not
a shortcut: duplicating `organization_id` onto `knowledge_items`, `content_items`, etc. would
create a second place those two columns could drift out of sync. Every query that needs
org-level scoping joins through `projects` — in practice this is always true anyway, since
the API is project-scoped in its URL structure (see `docs/api/API_DESIGN.md`).

**UUID primary keys everywhere.** Multi-project, eventually multi-org data will get merged,
exported, and referenced across systems (plugin webhooks, future data warehouse). UUIDs
avoid ID collisions across environments and don't leak row-count information the way
sequential integers do.

**No soft deletes.** Tables use explicit status enums (`project_status`,
`plugin_connection_status`, `content_item_status`, `contact_status`) instead of a generic
`deleted_at` column. A generic soft-delete flag invites every query in the codebase to forget
to filter it; explicit status enums make the valid states visible in the schema itself and
force each table's queries to handle its actual state machine, not a bolted-on deletion
concept. Data that must never disappear (e.g. `knowledge_items`, `agent_runs`, `domain_events`)
simply has no delete path at all.

**A native Postgres enum is used only for a core-owned, closed taxonomy — never for anything
a plugin package contributes values to.** `buying_intent` and `plugin_capability` are enums
because GrowthOS itself defines the complete, fixed set of valid values (four capability
Protocols; four intent levels) — a plugin doesn't invent a fifth capability kind, it just
implements a subset of the four that exist. `content_items.type`, by contrast, is `text`,
because the set of valid content types is defined by whichever plugins are currently
installed, not by core schema — see `docs/decisions/0008-plugin-contributed-content-types.md`.
**This distinction is the single most important rule for extending this schema**: before
adding a new enum, ask whether a future plugin could ever need to contribute a new value to
it. If yes, it's `text`, validated at the application layer against the plugin catalog. If
no — the taxonomy is closed and core-owned — an enum is correct and preferred.

**JSONB for genuinely variable, project- or plugin-specific shape; real columns and enums for
everything core-owned that's queried, filtered, or joined on.** `projects.icp_config`,
`agent_configs.config`, and `plugin_connections.config` are JSONB because their shape varies
per project/agent/plugin and isn't something core schema needs to constrain — each is
validated against its owner's own schema (a pydantic model) at the application layer instead.

## Table-by-table notes

### `organizations`, `users`, `memberships`
Deliberately minimal for v1 — one org, one user, `role` defaults to `owner`. The
`membership_role` enum already includes `member` so that Phase 4 (multi-tenant activation,
see `ROADMAP.md`) is a matter of *using* the existing model, not changing it.

### `projects`
The unit everything else hangs off. `icp_config` and `brand_voice` are JSONB because their
schema is intentionally agent/product-specific — e.g. ScoutSEO's ICP config might describe
"SaaS founders with Search Console access," while a future e-commerce project's ICP config
looks nothing like that. Agents read these fields; they don't assume a fixed shape.

### `plugin_catalog`
New in V2. Mirrors the in-process plugin manifest scan performed at every startup (see
`docs/plugins/PLUGIN_ARCHITECTURE.md` §Discovery) — this table is *derived*, refreshed
wholesale on each process start, never hand-edited. It exists so the API and frontend can
answer "what plugins exist and what do they need to connect" (`config_schema`) and "what
content types can this plugin publish" (`content_types`) without importing plugin Python
code into a request path. `plugin_connections.plugin_key` is validated against this table's
keys at the application layer, deliberately not a hard foreign key — a hard FK would create
ordering problems every time the catalog is rebuilt at startup (connections must never be
allowed to be silently deleted or fail to load because the catalog rebuild is mid-flight).

### `plugin_connections`
One row per (project, plugin, label) — `label` (default `"default"`) exists specifically so
a project can hold more than one connection to the same plugin (two Reddit accounts, two
Slack workspaces) without weakening the one-row-per-plugin case, which needs no special
handling. `capabilities_enabled` is explicit and separate from what the plugin *code*
declares in `plugin_catalog.capabilities` — a project might have valid Reddit credentials
capable of posting, but the user has deliberately not enabled `publishable` for it yet. This
is a second, project-level safety gate on top of the plugin's own capability contract,
checked in addition to, not instead of, the code-level structural check (see
`docs/plugins/PLUGIN_ARCHITECTURE.md` §"Two independent gates"). New in V2: `config` (JSONB,
validated against `plugin_catalog.config_schema` — the subreddit allowlist, OAuth scopes,
etc. that used to have no home and risked being duplicated into agent config) and the
envelope-encryption columns (`credentials_encrypted` now paired with
`credential_data_key_wrapped` — see `docs/security/SECURITY.md`). Added alongside the OAuth2
framework (`docs/auth/OAUTH2_ARCHITECTURE.md`, ADR 0011): `token_expires_at` and
`granted_scopes`, both **plaintext** — neither is a credential, and keeping them outside the
encrypted envelope is what lets the refresh sweep query by expiry and a status API answer
"what did this authorize" without any decrypt call; the `expired` status value, distinct from
`error`, separates "will self-heal via background refresh" from "needs a human to
reconnect."

### `agent_configs` / `agent_runs`
`agent_configs` is the enable/schedule/config record; `agent_runs` is the append-only audit
trail of every execution, whether schedule-triggered or event-subscription-triggered. This
split exists because a config is mutable state (you can change a schedule) while a run is an
immutable historical fact. `agent_runs.summary` (JSONB) is what the orchestrator reads to
assemble the Daily Brief — see `docs/knowledge-base/KNOWLEDGE_BASE.md` for its shape.

### `domain_events`
New in V2 — the transactional outbox agents communicate through instead of calling each
other or polling one another's tables. See `ARCHITECTURE.md` §7 and
`docs/decisions/0006-event-driven-agent-communication.md`. The load-bearing property: every
insert into this table happens in the same transaction as the row it describes, so an event
can never be lost to a "row committed, event publish failed separately" race. Retained
permanently (no delete path) — it doubles as a debuggable audit trail of "what triggered
what." The partial index on `dispatched_at is null` keeps the dispatcher's hot-path query
cheap regardless of total table size, since dispatched rows (the overwhelming majority over
time) never need to be scanned again for that purpose.

### `audit_log`
New in V2 (design review §5.3). Deliberately separate from `content_items`' review trail:
that table proves a specific human approved a specific piece of content; this one
reconstructs account-level security events (login, plugin connect/disconnect, credential
rotation) for incident response. Different purpose, different query pattern
(`(org_id, created_at)` for "what happened to this account recently," not
"what happened to this content item") — not worth conflating into one table.

### `knowledge_items`
The long-term institutional memory described in the original vision. `embedding` (pgvector)
enables semantic queries like "what problems are SaaS founders discussing most often" without
requiring exact tag matches. `unique(project_id, url)` prevents the same discovered thread
from being re-ingested by every daily run — an agent re-encountering a known URL should
enrich the existing row (e.g. update `outcome`), not create a duplicate. Every insert here
publishes a `knowledge_item.created` domain event in the same transaction — see
`docs/knowledge-base/KNOWLEDGE_BASE.md`.

`title`/`body_excerpt`/`platform_metadata` were added in Phase 2B (see
`docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md`), alongside Conversation Finder's own
Phase 2A columns above — not part of the original V2 design, because no consumer needed
grounding text or a plugin-specific reference until Content Agent existed to draft from one.
`platform_metadata` is an opaque passthrough of `PluginResult.platform_metadata`
(`plugins/_shared/base.py`); core schema and Conversation Finder never interpret it.

### `content_items`
The approval gate — see `ARCHITECTURE.md` §8 for the state machine itself.
`type` changed from a native enum to `text` in V2 — see the design-principles note above and
`docs/decisions/0008-plugin-contributed-content-types.md`; validated at the application layer
against `plugin_catalog.content_types`, not by the database. `version` is new in V2: an
optimistic-concurrency counter `ContentApprovalService` uses (`update ... where version =
:expected`) to guard the approve/reject transition against a concurrent double-transition —
closing design review §3.2. The `review_fields_consistent` check constraint remains enforced
at the database level in addition to the service layer: this is the one invariant where
"the application code should always get this right" isn't a strong enough guarantee for what
it protects (proof that a human, specifically, approved this content).

`confidence`/`reasoning`/`evidence` were added in Phase 2B alongside Content Agent — the
drafting agent's own self-assessment (`confidence` mirrors `knowledge_items.confidence`'s
0-1 shape but means "how good the agent judges its own draft to be"), and a JSON array of
short quotes (`evidence`) grounding the draft in its source `knowledge_item`, for a human
reviewer to scan quickly. See `docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md`.

### `companies` / `contacts`
Deliberately CRM-*lite*. This is what Customer Finder and Outreach Assistant need to track
ICP-matched targets and outreach status — it is not trying to be a full CRM. `contacts` links
to `companies` optionally because not every discovered contact (e.g. a Reddit username) has a
known company yet.

### `competitors` / `competitor_observations`
Split for the same reason as `agent_configs`/`agent_runs`: `competitors` is the (mutable,
small) list of who you're tracking; `competitor_observations` is an append-only log of what
Competitor Watch found over time.

### `daily_briefs`
One row per (project, date) — the materialized view the dashboard renders, now assembled by
the orchestrator's subscription to `project.daily_cycle.completed` rather than a timeout
heuristic (see `agents/orchestrator/README.md`).

## Migrations

`database/schema.sql` is the design source of truth. Actual schema changes ship as Alembic
migrations under `backend/migrations/`, generated from SQLAlchemy models that mirror this
file. When they diverge, this file is wrong and should be updated to match the migrations —
migrations are what actually ran against production.

## What's intentionally not here yet

- Billing/subscription tables (Phase 4, see `ROADMAP.md`).
- Full-text search indexes beyond the vector index (add when the knowledge base is large
  enough that semantic search alone isn't sufficient — premature to index for now).
- Row-Level Security policies — planned for Phase 4 when a second org's data actually shares
  infrastructure with the first; for a single-org deployment, application-layer scoping
  (every query filtered by `project_id` via the service layer) is sufficient and simpler to
  reason about. See `docs/security/SECURITY.md`.
- A hard foreign key from `plugin_connections.plugin_key` to `plugin_catalog.plugin_key` —
  deliberately validated at the application layer instead; see the `plugin_catalog` note
  above.
