# Orchestrator

**Phase:** 1 · **Produces content:** no · **Plugins used:** none directly
**Version 2:** narrowed role — no longer owns cross-agent sequencing; see
`docs/decisions/0006-event-driven-agent-communication.md`.

## Purpose

The orchestrator is not a research or content agent, and — as of the V2 architecture — it is
no longer the component responsible for agent-to-agent ordering either. That responsibility
moved to each agent's own `subscriptions.py` (see `docs/agents/AGENT_ARCHITECTURE.md`
§Communication). What's left is what's genuinely time-based and has no upstream event to
react to: cron scheduling and Daily Brief assembly.

## Responsibilities

1. **Scheduling.** Reads `agent_configs` for every active project and enqueues an Arq job per
   enabled agent according to its `schedule_cron` — for agents that originate a cycle
   (`conversation_finder`) rather than react to one.
2. **Daily Brief assembly.** Subscribes to `project.daily_cycle.completed` (published once a
   project's scheduled agents for the day have all reached a terminal state) and assembles a
   `daily_briefs` row from that day's `agent_runs.summary` values — itself just another event
   subscriber, using the same mechanism every other agent uses, not a special case.
3. **On-demand runs.** Exposes the entry point the API uses for "re-run this agent now."

**What it no longer does:** decide which agents run before which other agents. Under the
original design this was a hand-authored, per-project sequencing config the orchestrator
owned and enforced. That coupling is gone — `content_agent` declaring a subscription to
`knowledge_item.created` *is* the dependency, expressed where it belongs (in the dependent
agent's own package), not in a third component that both agents had to be aware existed.

## Reads

`projects`, `agent_configs`, `domain_events` (specifically, `project.daily_cycle.completed`
events it's subscribed to), `agent_runs` (to determine what's terminal, for daily-cycle
completion detection).

## Writes

`agent_runs` (queues schedule-triggered runs — the actual row content comes from the agent
that ran), `daily_briefs`.

## Config

No more sequencing config. What remains is genuinely simple:

```json
{
  "daily_cycle_agents": ["conversation_finder", "competitor_watch", "customer_finder"],
  "brief_assembly_timeout_minutes": 30
}
```

`daily_cycle_agents` is the list the orchestrator watches for completion before publishing
`project.daily_cycle.completed` — it is not an execution order, just a "these are the
schedule-originated agents this project's morning cycle consists of" declaration.

## Notes

The orchestrator deliberately has no LLM calls of its own — pure scheduling and event-driven
aggregation logic. A future version may use an LLM to write the Daily Brief's
natural-language summary from the structured `agent_runs.summary` data; that's additive and
doesn't change this document's responsibilities.
