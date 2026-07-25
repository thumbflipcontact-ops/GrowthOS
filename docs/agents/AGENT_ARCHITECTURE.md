# Agent Architecture

**Version 2** — updated following the Principal Engineer design review
(`docs/reviews/DESIGN_REVIEW.md` §2), which found the original "communicate only through the
data layer" model was implemented as hand-rolled polling (each agent inventing its own "what's
new" query against another agent's table) with no reactivity path for webhook-triggered
discovery. This version keeps the original conclusion — agents never call each other — and
replaces the mechanism with explicit domain-event subscriptions. See
`docs/decisions/0006-event-driven-agent-communication.md`.

## What an agent is

An agent is a self-contained, schedulable-or-event-triggered unit of capability — "find
conversations," "draft content," "watch competitors." Each agent lives in its own package
under `agents/` with its own config schema, prompts, tools, memory scope, and tests. Agents
are the thing described in `ARCHITECTURE.md` §2 constraint 3: independent, swappable, and
never coupled to each other in code.

## The common interface

```python
# agents/_shared/base.py
class AgentContext:
    project: Project
    config: dict              # this agent's agent_configs.config for this project
    plugins: PluginRegistry   # scoped to this project's enabled plugin_connections
    llm: LLMProvider           # Claude primary, OpenAI secondary — see docs/decisions/0004
    knowledge_base: KnowledgeBaseClient
    events: EventPublisher     # publishes domain events transactionally — see §Communication
    logger: structlog.BoundLogger

class AgentResult:
    knowledge_items_created: int
    content_items_created: int
    summary: dict              # structured, human-readable — feeds the Daily Brief
    errors: list[str]

class Agent(Protocol):
    key: str                    # matches agents/<key>/, agent_configs.agent_key
    config_schema: type[BaseModel]

    async def run(self, ctx: AgentContext) -> AgentResult: ...
```

An agent's `run()` is the only thing invoked — by the orchestrator on a schedule, or by the
event dispatcher when a subscribed event fires. Everything else — prompt construction, tool
definitions, memory retrieval, subscriptions — is internal to the agent's package.

## Anatomy of an agent package

```
agents/<name>/
├── README.md            Purpose, inputs, outputs, config schema — the "what and why"
├── config.py             Pydantic model: what a project configures to run this agent
├── agent.py               run(ctx) -> AgentResult — the entry point
├── subscriptions.py        EventSubscription declarations — what triggers this agent, if
│                            anything other than a schedule (see §Communication)
├── prompts/                 System/task prompt templates (versioned, not inline strings)
├── tools.py                  Tool/function definitions this agent's LLM loop can call
├── memory.py                  How this agent reads/writes its project-scoped memory, if any
└── tests/
    ├── test_agent.py            Behavior tests against a mocked plugin registry and LLM
    ├── test_config.py            Config schema validation tests
    └── test_subscriptions.py      Verifies subscription filters match/reject as intended
```

## Communication: domain events, not direct calls, not hand-rolled polling

An agent's only inputs are its own config, the plugin registry, and the knowledge base
client. It never receives a reference to another agent, and it never independently invents a
"give me what's new since I last checked" query against another agent's table.

When one agent's output should trigger another — e.g. Conversation Finder discovers a
thread, Content Agent should draft a reply — the connection is explicit, not implicit:

1. Conversation Finder writes a `knowledge_items` row **and**, in the same transaction (via
   `ctx.events`, a transactional outbox — see `ARCHITECTURE.md` §7), a `knowledge_item.created`
   domain event.
2. Content Agent declares a subscription in `agents/content_agent/subscriptions.py`:
   ```python
   SUBSCRIPTIONS = [
       EventSubscription(
           event_type="knowledge_item.created",
           filter=lambda payload: payload["buying_intent"] in ("medium", "high"),
       ),
   ]
   ```
3. The event dispatcher (an Arq periodic job) picks up the undispatched event and enqueues a
   Content Agent run for it, within one dispatch cycle.

If Conversation Finder is disabled for a project, Content Agent simply never receives that
event — no code in either agent changes. If a third agent is later added that also wants to
react to `knowledge_item.created`, it adds its own `subscriptions.py` — no edit to Content
Agent, Conversation Finder, or any central list.

**Webhook-triggered discovery works identically.** A webhook-received `handle_webhook()` call
writes its row and event in the same transaction a scheduled agent run would — there is no
special case for real-time versus scheduled discovery; both flow through the same dispatch
mechanism.

## Scheduling vs. subscription — an agent can have either or both

- **Schedule-only** (`agent_configs.schedule_cron` set, no subscriptions): agents that
  originate a cycle rather than react to one — `conversation_finder` has nothing upstream to
  subscribe to; it's the thing that starts the chain.
- **Subscription-only** (no schedule, `subscriptions.py` populated): agents that only ever
  react — `content_agent` doesn't need its own cron entry if everything it does is triggered
  by discovered knowledge.
- **Both:** an agent can run on a schedule *and* react to events — e.g.
  `knowledge_base_agent`'s enrichment pass might run nightly on a schedule *and* react
  incrementally to `content_item.published` events for faster outcome tracking.

## The orchestrator's narrowed role

Under the original design, the orchestrator held a hand-authored, per-project sequencing
config (a list of lists) expressing which agents ran before which others. That mechanism is
gone — subscriptions now express those dependencies, declaratively, in the dependent agent's
own package. The orchestrator's remaining job is what's genuinely time-based:

1. **Scheduling** — enqueuing schedule-only and both-mode agents per `agent_configs.schedule_cron`.
2. **Daily Brief assembly** — triggered by a `project.daily_cycle.completed` event (itself
   published once a project's scheduled agents for the day have all reached a terminal
   state), not a fixed timeout guess.
3. **On-demand runs** — the entry point the API uses for "re-run this agent now."

See `agents/orchestrator/README.md`.

## Memory

Unchanged from the original design: each agent may keep project-scoped memory beyond the
shared knowledge base (e.g. Outreach Assistant tracking follow-up history), in agent-specific
tables or a generic `agent_memory` key-value table. An agent's memory is its own — if one
agent needs another's state, it reads the shared data layer or subscribes to that agent's
events, never the other agent's private memory.

## Prompts and tools

Unchanged from the original design — prompts live in `agents/<name>/prompts/`, not inline
strings; tools are thin wrappers over the plugin registry and knowledge base client, and a
tool wrapping a plugin's `publish()` call is only ever exposed to the publish worker, never
to a content-drafting agent directly (see `ARCHITECTURE.md` §8).

## The agent roster

| Agent | Phase | Trigger | Purpose |
|---|---|---|---|
| `orchestrator` | 1 | n/a — the scheduler itself | Schedules agents, assembles the Daily Brief on `project.daily_cycle.completed` |
| `conversation_finder` | 2A (implemented) | Schedule | Finds relevant external discussions — see `docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md` |
| `content_agent` | 1 | Subscription (`knowledge_item.created`) | Drafts replies/articles/outreach as `content_items` |
| `customer_finder` | 2 | Schedule | Finds ICP-matched companies/contacts |
| `competitor_watch` | 2 | Schedule | Tracks competitor activity |
| `outreach_assistant` | 2 | Schedule | Prioritizes follow-ups |
| `knowledge_base_agent` | 2 | Schedule + subscription (`content_item.published`) | Enrichment and pattern-mining |
| `analytics_agent` | 3 (deferred) | TBD | Cross-agent performance patterns |
| `crm_assistant` | 3 (deferred) | TBD | Relationship management assistance |

Each agent's own `README.md` documents its config schema, subscriptions (if any), and what it
reads and writes.

## How to add a new agent

See `CONTRIBUTING.md` §"Adding a new agent." In short: copy an existing agent package as a
template, define config, implement `run()` against the shared context only, declare
`subscriptions.py` for anything it should react to (or leave it empty for schedule-only
agents), register one line in the orchestrator's *scheduling* config only if it needs a
schedule (subscription-only agents need no orchestrator-side registration at all — the
dispatcher discovers subscribers by scanning installed agent packages, the same pattern
plugins use for discovery), write tests including one full run against a mocked plugin
registry and one subscription-filter test.

## Testing

Every agent's test suite runs against a mocked `PluginRegistry`, a mocked/recorded
`LLMProvider` response, and — new in this version — a subscription-filter test asserting the
agent's `subscriptions.py` correctly accepts and rejects representative event payloads. See
`docs/testing/TESTING.md`.
