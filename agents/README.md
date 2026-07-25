# Agents

Independent units of capability, triggered by a schedule or by subscribing to domain events —
never by another agent calling them directly. See
[`docs/agents/AGENT_ARCHITECTURE.md`](../docs/agents/AGENT_ARCHITECTURE.md) for the full
design — the common interface, the event-subscription communication model, and the checklist
for adding a new one.

| Agent | Phase | Trigger | Purpose |
|---|---|---|---|
| [`orchestrator`](orchestrator/README.md) | 1 | Schedule + `daily_cycle.completed` | Schedules cycle-originating agents, assembles the Daily Brief |
| [`conversation_finder`](conversation_finder/README.md) | 1 | Schedule | Finds relevant external discussions |
| [`content_agent`](content_agent/README.md) | 1 | Subscription (`knowledge_item.created`) | Drafts replies/articles/outreach as `content_items` |
| [`customer_finder`](customer_finder/README.md) | 2 | Schedule | Finds ICP-matched companies/contacts |
| [`competitor_watch`](competitor_watch/README.md) | 2 | Schedule | Tracks competitor activity |
| [`outreach_assistant`](outreach_assistant/README.md) | 2 | Schedule | Prioritizes follow-ups |
| [`knowledge_base_agent`](knowledge_base_agent/README.md) | 2 | Schedule + subscription | Enrichment and pattern-mining |
| [`analytics_agent`](analytics_agent/README.md) | 3 (deferred) | TBD | Cross-agent performance patterns |
| [`crm_assistant`](crm_assistant/README.md) | 3 (deferred) | TBD | Relationship management assistance |

Each agent's own `README.md` documents its config schema, what it reads and writes, and the
plugins it depends on.
