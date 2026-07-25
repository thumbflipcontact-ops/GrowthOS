# ADR 0003: Agents communicate through data, never through direct calls

**Status:** Partially superseded by [0006](0006-event-driven-agent-communication.md) —
2026-07-25. This ADR's conclusion (no direct agent-to-agent calls) stands. Its *mechanism*
(orchestrator-sequenced polling of the data layer) is replaced by event subscriptions; see
0006 for the reasoning.

**Status (original):** Accepted — 2026-07-24

## Context

GrowthOS's agent roster (Customer Finder, Conversation Finder, Content Agent, etc.) has real
dependencies between some agents' outputs — Content Agent drafts replies to what Conversation
Finder discovers, Outreach Assistant's prioritization feeds what Content Agent drafts as
follow-ups. The question is how that dependency should be expressed in code.

Two options: (1) agents call each other directly (e.g. `content_agent` imports and invokes
`conversation_finder`'s output-producing function), or (2) agents only ever read/write the
shared data layer, and an external orchestrator sequences their execution order.

## Decision

Option 2. Agents never import or call each other. All cross-agent "communication" happens by
one agent writing rows (`knowledge_items`, `contacts`, etc.) that another agent later reads
as part of its own independent `run()`. Execution order, where it matters, is expressed as
orchestrator-level sequencing configuration (`docs/agents/AGENT_ARCHITECTURE.md`,
`agents/orchestrator/README.md`) — not as a function call from one agent's code into
another's.

## Consequences

**Positive:** any agent can be disabled, deleted, or replaced without touching any other
agent's code — verified concretely by Phase 1's "delete an agent's package and nothing else
breaks" property (`ARCHITECTURE.md` §2). Testing is simpler: each agent's tests mock the data
layer and plugin registry, never another agent. Onboarding a second project (Phase 3) that
enables a different subset of agents requires zero code changes, only configuration.

**Accepted trade-off:** this pattern is eventually-consistent, not transactional — if
Conversation Finder's run for a project fails partway through, Content Agent's subsequent
run simply sees whatever knowledge items did get written, not a guaranteed complete set. This
is judged acceptable because agent runs are idempotent and repeat daily (`docs/jobs/BACKGROUND_JOBS.md`)
— a partial miss today is caught by tomorrow's run — but would need revisiting if a future
requirement demanded strict same-cycle completeness between dependent agents.
