# Roadmap

This roadmap is organized by phase, not by date. Each phase has an explicit exit criterion —
we move on when the criterion is met, not when a calendar date arrives. Anything not listed
under a phase is deliberately out of scope for that phase; see §Deferred for what's excluded
and why.

## Phase 0 — Foundation (complete)

Design documentation, a Principal Engineer design review, and the resulting Version 2
architecture. No product code — see `ARCHITECTURE_FREEZE.md` at the repo root for the freeze
declaration.

**Exit criterion (met):** architecture reviewed adversarially
(`docs/reviews/DESIGN_REVIEW.md`), revised (`ARCHITECTURE.md`, now Version 2), locked
(`docs/architecture/LOCKED_DECISIONS.md`), and audited for internal consistency across the
repository. See `ARCHITECTURE_FREEZE.md`.

## Phase 1 — Single-project skeleton

Goal: prove the core loop end-to-end for one project (ScoutSEO), with one plugin and two
agents, on the V2 foundation — built once, in the order below, not built against V1 and
reworked. This ordering is what the (now-archived) V1→V2 migration plan produced; see
`docs/architecture/archive/MIGRATION_V1_TO_V2.md` for the full reasoning behind each step.

1. **Schema foundation** — `database/schema.sql` as it stands today (V2 shape: no
   `content_item_type` enum, `plugin_catalog`, `domain_events`, `plugin_connections.config`,
   `content_items.version`, `audit_log` all present from the start).
2. **Plugin core** — manifest/entry-point discovery, the four segmented capability Protocols,
   the `PluginCatalog` scanner, `plugin_connections.config` validation. Exit check: a trivial
   test plugin is discoverable and shows up via `GET /api/v1/plugins/catalog` before any
   Reddit-specific code exists.
3. **Event core** — `domain_events` outbox, `EventPublisher`, the Arq event-dispatch
   periodic job, `agents/_shared/subscriptions.py`. Exit check: a published test event
   reaches a subscribed test handler within one dispatch cycle, and survives a simulated
   dispatcher crash mid-cycle.
4. **Reddit plugin** — `plugins/reddit/`, against the mechanism built in step 2, not a
   hand-registered one-off. See `plugins/reddit/README.md` and
   `docs/decisions/0005-first-plugin-reddit.md`.
5. **Conversation Finder + Content Agent** — Conversation Finder remains schedule-triggered
   (it originates discovery); Content Agent subscribes to `knowledge_item.created` instead of
   being placed in a sequencing config.
6. **Approval Inbox + publish worker** — `ContentApprovalService` with the `version`-column
   concurrency guard included from the start, not retrofitted.
7. **Credential encryption** — envelope encryption built as part of the plugin connection
   flow, before real Reddit OAuth tokens are ever stored.
8. **Observability** — OpenTelemetry spans on plugin calls and agent runs, wired to
   Prometheus/Grafana per `docs/observability/OBSERVABILITY.md`. Trails steps 1–7 slightly but
   ships within Phase 1, not deferred indefinitely.

**Exit criterion:** a real Reddit thread gets discovered, a reply gets drafted, you approve
it in the dashboard, and it posts to Reddit for real. This is the smallest slice that proves
the entire trust model (human-in-the-loop, approval state machine, plugin capability
contract, event-driven reactivity) works, not just on paper.

## Phase 2 — Full agent roster, one project

- Remaining agents: Customer Finder, Competitor Watch, Outreach Assistant, Knowledge Base
  Agent (the others are Phase 3, see below).
- Remaining plugins for ScoutSEO's actual channels: LinkedIn, Twitter/X, Search Console,
  Google Analytics, WebmasterWorld — `google_analytics` and `search_console` implement
  `MetricsQueryable`, not `Searchable` (see `docs/plugins/PLUGIN_ARCHITECTURE.md`).
- Orchestrator: the daily cron cycle and `project.daily_cycle.completed`-triggered Morning
  Brief assembly — no sequencing config to build, since each new agent declares its own
  event subscriptions in its own package.
- Frontend: Morning Brief view, Knowledge Base explorer, the generic
  `DynamicConnectionForm`-based plugin connection management (one component serving every
  plugin added from here on, per `docs/decisions/0009-plugin-config-schema-dynamic-ui.md`).

**Exit criterion:** GrowthOS runs unattended every morning for ScoutSEO and the Morning
Brief is something you'd actually open before coffee, not something you'd ignore.

## Phase 3 — Second project + deferred agents

- Onboard a second SaaS business as a second Project — this is the real test of the
  "nothing hardcoded for ScoutSEO" constraint from `ARCHITECTURE.md`. If this requires
  touching `agents/` or `backend/` core code, Phase 2 had a leak and it gets fixed here.
- **Analytics Agent** and **CRM Assistant** — deferred to this phase deliberately (see
  §Deferred) because they depend on knowledge base and customer data volume that doesn't
  exist until Phase 1–2 have been running for a while.
- Remaining plugins: Slack, Discord, Email, GitHub, generic CRM.

**Exit criterion:** two unrelated SaaS products both run on GrowthOS with zero
project-specific code changes.

## Phase 4 — Multi-tenant activation (only if you decide to sell GrowthOS)

Everything here was deliberately built cheaply-activatable in Phase 0–1 rather than bolted
on later — see `docs/decisions/0001-multi-tenancy.md`.

- Signup flow, org invitations, role-based access beyond single-owner.
- Billing integration.
- Per-org resource limits and rate limiting.
- Tenant isolation audit (see `docs/security/SECURITY.md`).

**Exit criterion:** a second, unrelated human can sign up, connect their own plugins, and
run GrowthOS for their own business with zero visibility into your data.

## Deferred, with reasoning

| Item | Why deferred |
|---|---|
| Analytics Agent | Needs enough historical `knowledge_items`/`content_items` volume to find real patterns. Building it against empty tables means designing against guesses. |
| CRM Assistant | Depends on Customer Finder and Outreach Assistant having run long enough to produce real relationship state worth assisting with. |
| Multi-tenant signup/billing | Solo-first per your call in Phase 0. Schema and auth are tenant-ready; the flows themselves are not built until there's a reason to sell seats. |
| Kubernetes | Docker Compose is correct for one operator's workload. Revisit only if/when Phase 4 activates and concurrent-tenant load actually requires it — see `docs/scalability/SCALABILITY.md`. |
| Mobile app | Nothing in the vision requires it yet; the dashboard is a morning-coffee check-in, not a mobile-first workflow. |
| Fine-tuned/self-hosted models | Provider abstraction (Claude + OpenAI) is deliberately in place so this is a future swap, not a rewrite, if cost or latency ever demands it. |
| Plugin sandboxing/isolation | Current trust model assumes first-party, reviewed plugin code only — a hard prerequisite before accepting any plugin not personally written/reviewed, not before then. See `docs/plugins/PLUGIN_ARCHITECTURE.md` §Trust model. |
| Dedicated event broker (Kafka/NATS) | The transactional-outbox-plus-Arq approach (`ARCHITECTURE.md` §7) is deliberately chosen over a dedicated broker at this scale. Revisit only if event volume or fan-out breadth grows by orders of magnitude — see `docs/scalability/SCALABILITY.md`. |

## Non-goals (permanent, not just deferred)

- **Autonomous publishing.** GrowthOS will never post, message, or publish without a human
  approval transition, at any phase, for any plugin. This is not a v1 limitation — see
  `ARCHITECTURE.md` §8.
- **Being a generic marketing automation platform.** GrowthOS is opinionated about the
  human-in-the-loop model; if that constraint is ever removed to chase a broader market,
  it's a different product.
