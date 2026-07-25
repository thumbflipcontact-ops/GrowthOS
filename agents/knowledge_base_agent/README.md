# Knowledge Base Agent

**Phase:** 2 · **Produces content:** no · **Trigger:** schedule (broad periodic enrichment
pass) + subscription (`content_item.published`, for faster per-item outcome tracking)
**Plugins used:** none directly for discovery; queries a `content_item`'s originating
`Searchable` plugin to check outcome signals

## Purpose

Runs enrichment and pattern-mining over the accumulated `knowledge_items` table. This is the
agent that eventually answers "what problems are SaaS founders discussing most often" and
"what content ideas have appeared repeatedly" — questions that require looking across many
knowledge items, not producing new ones.

## How it works

1. **Enrichment:** on a nightly schedule (broad sweep) and reactively via a
   `content_item.published` subscription (fast path for a single just-published item),
   checks `content_items` for outcome signals (did a published Reddit reply get
   upvoted/replied to?) via the originating plugin's `Searchable` capability, and updates
   `knowledge_items.outcome`.
2. **Pattern mining:** clusters `knowledge_items` by embedding similarity and tag overlap,
   and uses the LLM to summarize recurring themes — feeding `suggested_article` and
   `suggested_product_idea` fields where a cluster is strong enough to justify a suggestion
   that spans multiple observed conversations rather than one thread's own drafted
   suggestion.
3. Writes summaries consumable by the frontend's Knowledge Base Explorer view, not just the
   Daily Brief — this is the agent whose output is meant to be queried on demand, not only
   read once each morning.

## Reads

`knowledge_items` (broad, cross-record queries), `content_items` (outcome enrichment).

## Writes

`knowledge_items` (updates: `outcome`, occasionally `suggested_article` /
`suggested_product_idea` on the representative item of a cluster).

## Config

```json
{
  "enrichment_lookback_days": 30,
  "min_cluster_size_for_pattern": 3
}
```

## Notes

This agent is what makes the knowledge base a system of *insight*, not just a system of
*record*. Phase 1 ships without it — knowledge accumulates from day one regardless — but the
value of "months later GrowthOS should be able to answer..." compounds specifically because
this agent exists once there's enough data for its clustering to be meaningful.
