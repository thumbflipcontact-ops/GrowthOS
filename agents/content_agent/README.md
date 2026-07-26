# Content Agent

**Phase:** 2B/2C (implemented — see docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md and
docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md)
· **Produces content:** yes — created `draft`, auto-advanced to `pending_review` by its own
self-check; never advances a draft any further than that itself · **Trigger:** subscription
(`knowledge_item.created`, unconditionally — see `subscriptions.py` and §"What this agent
does not do" for why the original buying-intent filter isn't used yet)
**Plugins used:** none directly — this agent never calls a plugin's `search()`/`publish()`;
`target_platform`/`target_ref` are derived from the triggering `knowledge_item`'s own
`platform`/`platform_metadata`, not a live plugin call.

## Purpose

Reads a specific, newly-discovered `knowledge_item` and drafts one Reddit reply for it,
grounded in that item's own captured title/body text, via the configured LLM provider
(`docs/decisions/0004-llm-provider-abstraction.md`). Every draft is persisted as a
`content_items` row with the model's own confidence, reasoning, and quoted evidence
attached, then immediately self-checked and — if it passes — advanced to `pending_review`
for a human to review (`ContentApprovalService`, Phase 2C). This agent cannot advance
anything past `pending_review` itself, by construction: nothing in `agent.py` or
`ContentDraftClient` ever sets `content_items.status` to `approved`/`rejected`/`archived`/
`published` — those transitions belong exclusively to `ContentApprovalService` and the
publish worker.

## How it works

1. The event dispatcher invokes this agent with the specific `knowledge_item.created`
   event's payload (`ctx.trigger_payload`) — never by polling for "recent, undrafted"
   items. See `docs/agents/AGENT_ARCHITECTURE.md` §Communication.
2. Loads the triggering `knowledge_item` via `ctx.knowledge_base.get(knowledge_item_id)`.
3. Skips (records a reason in `AgentResult.errors`, drafts nothing) if: the item's platform
   isn't `"reddit"` (see below), its `confidence` is below this agent's
   `min_confidence_for_reply`, or it has no `title`/`body_excerpt` to draft or cite from.
4. Builds a prompt (`prompts/reddit_reply.py`) from the item's title/body excerpt/tags and
   the project's `brand_voice`, and calls `ctx.llm.complete(...)`.
5. Parses the model's response into `reply`/`confidence`/`reasoning`/`evidence` — a JSON
   response contract this agent's own prompt defines and enforces by parsing, not a
   provider-specific structured-output mechanism (ADR 0004's "common subset" trade-off).
   A response that fails to parse is a soft failure: recorded in `AgentResult.errors`, no
   `content_items` row written, run still `succeeded`.
6. Persists the draft via `ctx.content.create_draft(...)` (always `status="draft"`) —
   `target_ref` is the Reddit `thing_id` read from `knowledge_item.platform_metadata`
   (Reddit-specific knowledge that belongs in this agent's own code, not core platform
   code — see `docs/plugins/PLUGIN_ARCHITECTURE.md`'s "no plugin-specific logic outside the
   plugin" rule, which this agent's Reddit-awareness doesn't violate: it's an *agent*
   reading a documented-as-opaque field for its own purposes, not platform code branching on
   a `plugin_key`).
7. Immediately calls `ctx.content.submit_for_review(...)`, which runs the self-check
   (`app/services/content_self_check.py` — non-empty body, within `max_reply_length`, no
   `banned_phrases`) against the drafted body. A passing check advances the row to
   `pending_review` (matching ARCHITECTURE.md §8's documented flow exactly); a failing check
   leaves it in `draft`, with the specific reasons recorded in `AgentResult.summary` — not on
   the row itself, since `content_items` has no dedicated "why" column for this (see
   `docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md`).

## What this agent does not do

The original spec for this agent (still described above where it still applies) also
describes outreach drafts (subscribing to `contact.followup_due`) and standalone article
drafts (schedule-driven, cross-`knowledge_item` pattern mining). **Neither is built.** This
agent is reply drafts only, for Reddit only — no `contacts` table integration, no article
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

**No duplicate-content check.** ARCHITECTURE.md §8's self-check example also names a
duplicate-content check against recent `content_items`. Not implemented — it's a materially
bigger feature (a similarity comparison, not a pure length/phrase check) than the rest of
the self-check; noted as remaining work in
`docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md`, not silently dropped.

## Reads

`knowledge_items` (the triggering item, by id, via `ctx.knowledge_base.get`),
`projects.brand_voice`.

## Writes

`content_items` (creates a new `draft` row, then — via the self-check — may advance that
same row to `pending_review`; never touches any other row, never sets any other status).

## Config

```json
{
  "min_confidence_for_reply": 0.4,
  "max_reply_length": 10000,
  "temperature": 0.7,
  "max_tokens": 1024,
  "banned_phrases": []
}
```

Set via `PUT /api/v1/projects/{project_id}/agent-configs/content_agent` — see
`docs/api/API_DESIGN.md`. `max_reply_length` is a static number matching
`plugins/reddit/manifest.py`'s declared `reddit_reply` content type max length, not read from
the plugin catalog dynamically — a deliberate simplification for this agent's
single-platform scope. `banned_phrases` is empty by default — no phrase is banned unless a
project configures one; this is real, generic self-check infrastructure, not a specific
content policy invented for this task. No `schedule_cron` is meaningful here — this agent is
subscription-only and never appears in the cron scheduler's poll.
