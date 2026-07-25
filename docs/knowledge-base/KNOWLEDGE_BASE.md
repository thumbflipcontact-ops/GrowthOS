# Knowledge Base Design

**Version 2** — every insert now also publishes a `knowledge_item.created` domain event in
the same transaction; §Two ways the knowledge base gets queried below is updated to reflect
event subscription replacing polling. See `ARCHITECTURE.md` §7.

## What it is

The `knowledge_items` table (`docs/database/SCHEMA.md`) is GrowthOS's answer to the vision's
core promise: every conversation discovered online becomes structured, permanent,
queryable knowledge — not a transient log line, not a Slack message that scrolls away.
Months later, GrowthOS should be able to answer "what problems are SaaS founders discussing
most often" or "what content ideas have appeared repeatedly" by querying this table, not by
someone remembering.

## Structure

| Field | Purpose |
|---|---|
| `platform`, `url` | Where this was found — also the dedup key (`unique(project_id, url)`) |
| `problem`, `industry`, `product`, `pain_point` | The structured extraction an LLM call performs on the raw discovery |
| `buying_intent` | Enum classification (`none`/`low`/`medium`/`high`) — the single field the Daily Brief sorts by first |
| `suggested_reply`, `suggested_article`, `suggested_product_idea` | The agent's own suggestions at discovery time — not commitments, just what informed a `content_item` draft if one was created |
| `tags` | Free-form, agent-assigned, queried via GIN index — the mechanism for cross-cutting queries that don't map to a fixed field |
| `confidence` | How sure the extracting agent was — lets low-confidence noise be filtered out of the Daily Brief without being discarded from the table entirely |
| `outcome` | Filled in later by `knowledge_base_agent`'s enrichment pass — did anything come of this? |
| `embedding` | pgvector — enables "find conversations like this one" and clustering for pattern-mining, not just exact tag/keyword matches |

## Why every discovery gets saved, not just the good ones

A low-confidence, low-buying-intent item is still saved. Two reasons: first, "worth a human's
attention today" and "worth remembering" are different bars — a pattern only becomes visible
once enough individually-unremarkable data points accumulate (this is exactly what
`knowledge_base_agent`'s clustering is for). Second, saving selectively based on today's
judgment of relevance means permanently losing data that a later, better understanding of the
ICP might have found relevant. Storage is cheap; a lost data point is not recoverable.

## Two ways the knowledge base gets queried

1. **Point-in-time, agent-driven:** `conversation_finder` checks a URL against existing
   `knowledge_items` to avoid re-processing. `content_agent` no longer polls for "recent
   high-intent items with no linked content_item" — it subscribes to `knowledge_item.created`
   (filtered by `buying_intent`) and is invoked by the event dispatcher when one is published,
   reading only the specific item the event refers to. See `docs/agents/AGENT_ARCHITECTURE.md`
   §Communication and `ARCHITECTURE.md` §7 for why this replaced the original polling design.
2. **Broad, human- or `knowledge_base_agent`-driven:** "what problems come up most often this
   quarter," "show me everything tagged `pricing-objection`," "what's similar to this thread."
   This is what the Knowledge Base Explorer frontend view and `knowledge_base_agent`'s
   clustering pass are for — see `agents/knowledge_base_agent/README.md`.

## Relationship to `content_items`

A `knowledge_item` optionally informs a `content_item` (nullable FK,
`content_items.knowledge_item_id`) — optional because not all content is a reply to a
discovery (e.g. a proactively written article isn't responding to one specific thread). When
a `content_item` created from a `knowledge_item` gets published and later shows real-world
outcome (a Reddit reply got a reply back, an email got answered), that outcome flows back
into `knowledge_items.outcome` via `knowledge_base_agent`'s enrichment pass — closing the
loop from "we found this" to "here's what happened when we engaged with it," which is the
data that eventually makes GrowthOS's suggestions better over time, not just more numerous.

## Cross-project knowledge

Deliberately **not** shared across projects in v1 — a `knowledge_item` belongs to exactly one
`project_id`. ScoutSEO's discovered conversations about GSC don't pollute a future project's
knowledge base. A founder-level, cross-project pattern view ("what do I keep hearing across
all my businesses") is a plausible Phase 3+ feature once there are two real projects'
worth of data to compare — but it would be a deliberate cross-project *query* built on top of
the existing per-project isolation, not a change to how knowledge is stored.
