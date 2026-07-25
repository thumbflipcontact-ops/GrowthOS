# Outreach Assistant

**Phase:** 2 · **Produces content:** indirectly (triggers `content_agent` via a domain event)
**Trigger:** schedule · **Plugins used:** none directly

## Purpose

Reviews known `contacts` and decides who needs follow-up today, and why — "which customers
require follow-up." It is a prioritization and triggering agent, not a drafting agent: it
never writes `content_items` itself.

## How it works

1. Reads `contacts` and their `status`, plus timing signals (last contact date, tracked in
   its own agent memory keyed by `contact_id`).
2. Applies configurable follow-up rules (e.g. "no response after 5 days → follow up once,"
   "replied → prioritize for a personal touch").
3. For each prioritized contact, publishes a `contact.followup_due` domain event (payload:
   `contact_id`, `reason`) — this becomes both Daily Brief content (the orchestrator's
   Daily Brief assembly also reads recent events) and the trigger for `content_agent`, which
   subscribes to `contact.followup_due` in addition to `knowledge_item.created`
   (`agents/content_agent/README.md`). No polling on either side — see `ARCHITECTURE.md` §7.

## Reads

`contacts`, `companies`, its own agent memory (follow-up history).

## Writes

`domain_events` (`contact.followup_due`) and its own agent memory (no other shared tables) —
Outreach Assistant does not write `contacts` status changes itself, since that status
genuinely changes based on the human's actual outreach action, not this agent's opinion. See
`docs/agents/AGENT_ARCHITECTURE.md` on agent memory scoping.

## Config

```json
{
  "follow_up_after_days": 5,
  "max_follow_ups_per_contact": 3
}
```

## Notes

`max_follow_ups_per_contact` is a deliberate anti-spam guardrail baked into the agent's own
config, independent of and in addition to the human approval gate — GrowthOS should never
even *suggest* badgering a contact who's gone quiet four times.
