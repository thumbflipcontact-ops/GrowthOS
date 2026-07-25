# ADR 0006: Event-driven agent communication via transactional outbox + Arq dispatch

**Status:** Accepted — 2026-07-25. Supersedes the *mechanism* of ADR 0003 (its conclusion —
agents never call each other directly — is retained, not reversed).

## Context

ADR 0003 established that agents communicate only through the shared data layer, never
through direct calls. In practice this was implemented as polling: each agent's `run()`
independently queries for "new" rows it hasn't processed yet (e.g. `content_agent` querying
`knowledge_items` for "recent, high-intent, not yet linked to a content item"). A Principal
Engineer design review (`docs/reviews/DESIGN_REVIEW.md` §2) identified three problems with
this: every consumer reinvents its own polling/dedup logic against the producer's table
shape; webhook-capable plugins (`email`, `slack`, `discord`) have no path from "event
received" to "downstream agent notified," since nothing reacts to a webhook write in real
time; and the orchestrator's hand-authored per-project sequencing config doesn't scale
cleanly as the agent roster grows.

## Decision

Introduce a `domain_events` table as a **transactional outbox**: written in the same
database transaction as the row that causes it (e.g. a `knowledge_items` insert and its
`knowledge_item.created` event commit together, so the event can never be lost to a
publish-after-commit race). A lightweight Arq periodic job dispatches undispatched events to
subscribed handlers. Agents declare what they react to as data in their own package
(`agents/<name>/subscriptions.py`), not as an entry in a central sequencing list. The
orchestrator's responsibility narrows to genuinely time-based work: cron-triggered discovery
runs and Daily Brief assembly.

This deliberately does **not** introduce a dedicated message broker (Kafka, NATS, etc.) —
Postgres is the durable log, Arq (already in the stack per ADR 0002) is the dispatcher. See
`ARCHITECTURE.md` §7 for the full design (merged from the original V2 proposal, archived at
`docs/architecture/archive/ARCHITECTURE_V2_PROPOSAL.md`).

## Consequences

**Positive:** webhook-capable plugins get a real, non-special-cased reactivity path — a
webhook write and a scheduled agent's write both flow through the identical event mechanism.
Adding an agent that reacts to an existing event type requires no edit to any other agent's
code or to a central config. The transactional outbox pattern eliminates the specific
lost-event failure mode a naive "write row, then separately call publish()" approach would
have.

**Accepted trade-off:** event delivery is near-real-time, not instantaneous — bounded by the
dispatcher's poll interval (tunable; left flexible, see
`docs/architecture/LOCKED_DECISIONS.md` §2). This is judged acceptable because nothing in
GrowthOS's actual use case (a founder's morning workflow, plus webhook-triggered discovery
that's still reasonably tolerant of a few seconds' delay) requires sub-second delivery. If a
future requirement genuinely needs it, tightening the poll interval is a config change, not
an architecture change — and only if that proves insufficient would a dedicated broker
warrant reconsideration.

**What this does NOT change:** the conclusion of ADR 0003 (no direct agent-to-agent calls,
no shared in-memory state) is unchanged and reinforced — this ADR only replaces *how* an
agent discovers there's work to do.
