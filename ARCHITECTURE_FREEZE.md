# Architecture Freeze

**Date:** 2026-07-25
**Status:** Phase 0 complete. The architecture described here and in `ARCHITECTURE.md` is
frozen — implementation may begin against it. Changing a frozen decision after this point
requires a new ADR under `docs/decisions/` that explicitly supersedes the one being changed,
not a silent deviation during implementation.

## What happened in Phase 0

1. A complete architecture was designed and documented across `ARCHITECTURE.md` and the 20
   topics under `docs/` — the original foundation.
2. An independent Principal Engineer design review (`docs/reviews/DESIGN_REVIEW.md`)
   adversarially challenged every part of it against two explicit constraints: support 100+
   plugins over GrowthOS's lifetime with zero core-code changes per plugin, and evaluate
   whether agents should communicate through events rather than direct calls.
3. The review found the plugin architecture did not, in fact, meet the 100+ plugin
   requirement — four independent ways — and that the agent communication model had
   quietly become hand-rolled polling with no reactivity path for webhook-triggered
   discovery. Sixteen findings in total, three critical.
4. A revised architecture (Version 2) was designed to close every 🔴/🟠 finding, approved,
   and merged into the canonical documents — `ARCHITECTURE.md`, `docs/plugins/PLUGIN_ARCHITECTURE.md`,
   `docs/agents/AGENT_ARCHITECTURE.md`, `database/schema.sql`, and every document that
   referenced the parts that changed.
5. Superseded proposal and migration documents were archived (not deleted) under
   `docs/architecture/archive/`, with the frozen decision set consolidated in
   `docs/architecture/LOCKED_DECISIONS.md`.
6. A full repository consistency audit (§Audit below) verified no document contradicts
   another, no stale reference survives, and every cross-reference resolves correctly.

## The two questions this review had to answer

**Does the architecture support 100+ plugins with zero core changes?** As originally
designed, no. As frozen, yes — mechanically, not by convention: plugins are discovered via
self-describing manifests (entry points, not a hand-edited list), capabilities are segmented
Protocols instead of one interface gated by a runtime enum, publishable content types are
plugin-contributed (`text`, app-validated) rather than a closed database enum, and every
plugin's connection UI is generated from its own declared config schema instead of requiring
custom frontend code. See `ARCHITECTURE.md` §5–6 and ADRs 0007–0009.

**Should GrowthOS be event-driven?** Yes, in a specific and deliberately lightweight form.
Agents publish and subscribe to domain events through a Postgres transactional outbox,
dispatched via Arq — not a dedicated message broker. This replaced hand-rolled polling and a
hand-authored per-project sequencing config with something that scales with agent count
instead of against it, and gave webhook-triggered discovery a real reactivity path it
previously didn't have. See `ARCHITECTURE.md` §7 and ADR 0006.

## What implementation must follow

The complete, current architecture is `ARCHITECTURE.md` — this document does not restate it.
The full locked/flexible decision inventory (15 locked decisions, 8 explicitly left flexible
with reasoning for each) is `docs/architecture/LOCKED_DECISIONS.md`. In summary, what's
locked spans: tenant-ready multi-project scoping, Arq for jobs and event dispatch, agents
that never call each other, manifest-based plugin discovery, segmented plugin capability
Protocols, plugin-contributed content types, plugin-declared config schemas driving a generic
connection UI, envelope-encrypted credentials, a concurrency-guarded approval transition,
REST over GraphQL, Docker Compose over Kubernetes, and permanent human-in-the-loop publishing
with no exceptions at any phase.

Implementation begins at `ROADMAP.md` Phase 1, sequenced exactly as
`docs/architecture/archive/MIGRATION_V1_TO_V2.md` laid out: schema foundation, plugin core,
event core, the Reddit plugin, Conversation Finder and Content Agent, the Approval Inbox and
publish worker, credential encryption, observability — in that order, so the 100+ plugin and
event-driven foundations are built once, correctly, rather than built naively and reworked.

## Audit

A full-repository consistency pass was performed after the V2 merge — a systematic grep
sweep for every stale term the merge could plausibly have left behind
(`content_item_type`, `BasePlugin`, `CREDENTIAL_ENCRYPTION_KEY`, `READ`/`PUBLISH`/`WEBHOOK`
as capability names, "sequencing config," "register... the registry," and stale `§5`
section references), file by file, with every hit individually triaged as either a correct
historical/explanatory reference (left alone — the design review and archived documents are
supposed to describe what V1 used to say) or a live inconsistency (fixed). The second pass
found and corrected roughly fifteen real stragglers the first merge pass missed, including:
`ARCHITECTURE.md` §5 references that pointed at the approval state machine before the merge
inserted new sections ahead of it and moved it to §8 (fixed across seven files); three ADRs
and the design review itself still linking to `docs/architecture/ARCHITECTURE_V2.md` and
`MIGRATION_V1_TO_V2.md` at their pre-archive path (fixed to point at
`docs/architecture/archive/`); `customer_finder` and `competitor_watch`'s READMEs still
describing plugins as `READ`-capable instead of `Searchable`/`MetricsQueryable`; and
`outreach_assistant`'s README describing `content_agent` polling its output instead of
subscribing to a `contact.followup_due` event, which also required adding that event
explicitly to `content_agent`'s own trigger list for the two documents to agree. Checking:

- **Every document agrees with the canonical architecture.** Every doc that referenced the
  old plugin registry, the `BasePlugin` single interface, `content_item_type` as an enum,
  orchestrator sequencing config, or the flat `CREDENTIAL_ENCRYPTION_KEY` was found and
  updated — `docs/plugins/PLUGIN_ARCHITECTURE.md`, `docs/agents/AGENT_ARCHITECTURE.md`,
  `database/schema.sql` and its `docs/database/` companions, `docs/api/API_DESIGN.md`,
  `docs/security/SECURITY.md`, `docs/auth/AUTHENTICATION.md`,
  `docs/jobs/BACKGROUND_JOBS.md`, `docs/deployment/DEPLOYMENT.md`,
  `docs/config/CONFIGURATION.md`, `.env.example`, `docker/docker-compose.yml`,
  `CONTRIBUTING.md`, `ROADMAP.md`, root `README.md`, `docs/scalability/SCALABILITY.md`,
  `docs/knowledge-base/KNOWLEDGE_BASE.md`, `docs/errors/ERROR_HANDLING.md`, every plugin
  `README.md`, and every agent `README.md`.
- **No outdated diagrams.** The system diagram in `ARCHITECTURE.md` §3 and the ERD in
  `docs/database/ERD.md` both reflect `domain_events`, `plugin_catalog`, `audit_log`, and the
  revised `content_items`/`plugin_connections` columns.
- **No conflicting ADRs.** ADR 0003 is explicitly marked superseded (mechanism only — its
  conclusion stands) by ADR 0006. ADRs 0007–0010 are new and consistent with each other and
  with `ARCHITECTURE.md`. `docs/decisions/README.md`'s index reflects current status for all
  ten.
- **Every cross-reference points to the correct document.** References to the old
  `ARCHITECTURE.md` §5 (approval state machine) were updated to §8 throughout, since the
  section moved when plugin/event architecture sections were inserted. References to
  `ARCHITECTURE_V2.md` and `MIGRATION_V1_TO_V2.md` were updated to their archived location.
- **The architecture is internally consistent.** The core-owned-vs-plugin-contributed
  taxonomy rule (enum vs. `text`) is stated once in `docs/database/SCHEMA.md` and applied
  consistently: `buying_intent` and `plugin_capability` stayed enums; `content_items.type`
  did not. The two-independent-gates rule for publishing (plugin capability + connection
  enablement) is stated consistently in `ARCHITECTURE.md`, `docs/plugins/PLUGIN_ARCHITECTURE.md`,
  and `docs/database/SCHEMA.md`. Agent trigger types (schedule vs. subscription vs. both) are
  applied consistently across `docs/agents/AGENT_ARCHITECTURE.md`'s roster table and every
  individual agent `README.md`, including propagating the `outreach_assistant →
  contact.followup_due → content_agent` event link that a purely mechanical find-replace
  would have missed.

**Result: pass.** No known contradiction, stale reference, or orphaned document remains as
of this freeze.

## Phase 0 is complete

See `ROADMAP.md` for what's next.
