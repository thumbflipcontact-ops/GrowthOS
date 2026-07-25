# Content Agent

**Phase:** 2B (implemented — see docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md)
· **Produces content:** yes — always as `draft`, never advanced further by this agent's own
code · **Trigger:** subscription (`knowledge_item.created`, unconditionally — see
`subscriptions.py` and §"What Phase 2B does not do" for why the original buying-intent
filter isn't used yet)
**Plugins used:** none directly — Phase 2B never calls a plugin's `search()`/`publish()`;
`target_platform`/`target_ref` are derived from the triggering `knowledge_item`'s own
`platform`/`platform_metadata`, not a live plugin call.

## Purpose

Reads a specific, newly-discovered `knowledge_item` and drafts one Reddit reply for it,
grounded in that item's own captured title/body text, via the configured LLM provider
(`docs/decisions/0004-llm-provider-abstraction.md`). Every draft is persisted as a
`content_items` row in `draft` status, with the model's own confidence, reasoning, and
quoted evidence attached — for a human to review later (Phase 2C). This agent cannot advance
a draft past `draft` itself, by construction: nothing in `agent.py` ever sets
`content_items.status` to anything but the model's own default.

## How it works

1. The event dispatcher invokes this agent with the specific `knowledge_item.created`
   event's payload (`ctx.trigger_payload`) — never by polling for "recent, undrafted"
   items. See `docs/agents/AGENT_ARCHITECTURE.md` §Communication.
2. Loads the triggering `knowledge_item` via `ctx.knowledge_base.get(knowledge_item_id)`.
3. Skips (records a reason in `AgentResult.errors`, drafts nothing) if: the item's platform
   isn't `"reddit"` (Phase 2B scope — see below), its `confidence` is below this agent's
   `min_confidence_for_reply`, or it has no `title`/`body_excerpt` to draft or cite from.
4. Builds a prompt (`prompts/reddit_reply.py`) from the item's title/body excerpt/tags and
   the project's `brand_voice`, and calls `ctx.llm.complete(...)`.
5. Parses the model's response into `reply`/`confidence`/`reasoning`/`evidence` — a JSON
   response contract this agent's own prompt defines and enforces by parsing, not a
   provider-specific structured-output mechanism (ADR 0004's "common subset" trade-off).
   A response that fails to parse is a soft failure: recorded in `AgentResult.errors`, no
   `content_items` row written, run still `succeeded` (see the implementation report for why
   this doesn't raise/retry).
6. Persists the draft via `ctx.content.create_draft(...)` — `target_ref` is the Reddit
   `thing_id` read from `knowledge_item.platform_metadata` (Reddit-specific knowledge that
   belongs in this agent's own code, not core platform code — see
   `docs/plugins/PLUGIN_ARCHITECTURE.md`'s "no plugin-specific logic outside the plugin"
   rule, which this agent's Reddit-awareness doesn't violate: it's an *agent* reading a
   documented-as-opaque field for its own purposes, not platform code branching on a
   `plugin_key`).

## What Phase 2B does not do

The original spec for this agent (still described above where it still applies) also
describes outreach drafts (subscribing to `contact.followup_due`) and standalone article
drafts (schedule-driven, cross-`knowledge_item` pattern mining). **Neither is built.** Phase
2B is reply drafts only, for Reddit only — no `contacts` table integration, no article
prompt template, no other plugin's reply format. `ContentAgentConfig` reflects this: no
`content_types_enabled` list (there's exactly one type), no `min_buying_intent_for_reply`
(see below).

**No `buying_intent`-based subscription filter.** The original design filters
`knowledge_item.created` events by `payload["buying_intent"] in (medium, high)`. Nothing
populates `buying_intent` yet — Conversation Finder (Phase 2A) has no LLM integration, so
every `knowledge_item` it writes has `buying_intent="none"`. A hardcoded filter on that field
would silently match zero events, forever. This agent instead subscribes unconditionally and
gates relevance inside `run()` against the item's `confidence` (a real, populated field) and
its own `min_confidence_for_reply` config.

**No self-check / no promotion to `pending_review`.** The original design has this agent run
a length/banned-phrase/duplicate-content self-check before advancing `draft → pending_review`.
This task's instructions are explicit: every draft stays in `draft` until a human explicitly
approves it, and the approval workflow itself is out of scope (Phase 2C). So there is no
promotion step at all yet — every draft this agent writes simply stays exactly where the
model default puts it.

## Reads

`knowledge_items` (the triggering item, by id, via `ctx.knowledge_base.get`),
`projects.brand_voice`.

## Writes

`content_items` (new `draft` rows only — this agent never updates an existing row).

## Config

```json
{
  "min_confidence_for_reply": 0.4,
  "max_reply_length": 10000,
  "temperature": 0.7,
  "max_tokens": 1024
}
```

Set via `PUT /api/v1/projects/{project_id}/agent-configs/content_agent` — see
`docs/api/API_DESIGN.md`. `max_reply_length` is a static number matching
`plugins/reddit/manifest.py`'s declared `reddit_reply` content type max length, not read from
the plugin catalog dynamically — a deliberate simplification for Phase 2B's single-platform
scope (see the implementation report). No `schedule_cron` is meaningful here — this agent is
subscription-only and never appears in the cron scheduler's poll.
