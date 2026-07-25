# Content Agent

**Phase:** 1 · **Produces content:** yes — always as `pending_review`, never published directly
**Trigger:** subscription (`knowledge_item.created` filtered by `buying_intent`, for reply
drafts; `contact.followup_due`, published by `outreach_assistant`, for outreach drafts) plus
a schedule for standalone article drafting (see below)
**Plugins used:** none directly for publishing (that's the publish worker's job — see
`ARCHITECTURE.md` §8); reads `plugin_catalog.content_types`/config to know target-platform
constraints (e.g. character limits)

## Purpose

Drafts replies, articles, and outreach copy. This is the agent that answers "what content
should I publish today" — but "publish" here always means "propose for your approval," never
"post." Every `content_item` this agent creates starts in `draft`, is self-checked, and
advances to `pending_review` — it can never reach `published` through this agent's own code
path.

## How it works

1. **Reply drafts:** subscribes to `knowledge_item.created`
   (`agents/content_agent/subscriptions.py`, filtered by `buying_intent`) — invoked by the
   event dispatcher with the specific triggering `knowledge_item`, not by polling for
   "recent, high-intent, unlinked" items itself. See
   `docs/agents/AGENT_ARCHITECTURE.md` §Communication for why this replaced polling.
2. **Outreach drafts:** subscribes to `contact.followup_due` (published by
   `outreach_assistant` — see `agents/outreach_assistant/README.md`), reading the specific
   `contact_id` and `reason` from the event payload.
3. **Article drafts:** separately, on its own schedule, can draft standalone articles from
   patterns found across many `knowledge_items` (e.g. "five founders asked about X this
   month" → article brief) — this doesn't have a single triggering event (it's a
   cross-item pattern, not a reaction to one row), so it stays schedule-driven.
4. Drafts using the project's `brand_voice` config and the target platform's constraints
   (from `plugin_catalog.content_types` for the target plugin).
5. Runs a self-check (length limits, a banned-phrase filter, a duplicate-content check
   against recent `content_items`) before advancing `draft → pending_review`. A failed
   self-check leaves the item in `draft` with the failure reason in its `summary`, for a
   human to inspect rather than silently discarding it.

## Reads

`knowledge_items`, `contacts` (for outreach drafts), `content_items` (dedup/self-check),
`projects.brand_voice`.

## Writes

`content_items` (status `draft` → `pending_review` only).

## Config

```json
{
  "content_types_enabled": ["reddit_reply", "linkedin_message", "article"],
  "max_drafts_per_run": 10,
  "min_buying_intent_for_reply": "medium"
}
```

## Notes

This agent is the clearest illustration of the human-in-the-loop constraint: it is
architecturally incapable of publishing anything, regardless of how confident it is. See
`ARCHITECTURE.md` §8 — the capability check happens at the plugin layer and the state-machine
enforcement happens at the service layer, not here, deliberately, so this agent's code cannot
be the thing that gets it wrong.
