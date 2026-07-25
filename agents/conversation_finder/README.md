# Conversation Finder

**Phase:** 1 · **Produces content:** no (produces knowledge, which content_agent drafts from)
**Trigger:** schedule (it originates a discovery cycle — nothing upstream to subscribe to)
**Plugins used:** any plugin implementing `Searchable`, e.g. `reddit`, `linkedin`, `twitter`,
`gsc_community`, `webmasterworld` — not `search_console`/`google_analytics`, which implement
`MetricsQueryable` instead (see `docs/plugins/PLUGIN_ARCHITECTURE.md`)

## Purpose

Searches the platforms a project has connected for discussions relevant to that project's
ICP and problem space, and converts anything worth engaging with into structured
`knowledge_items`. This is the agent that answers "which online discussions are worth
joining" and "which conversations show high buying intent."

## How it works

1. Builds search queries from the project's `icp_config` (problem keywords, industry,
   product category).
2. Calls `search()` on every connected plugin implementing `Searchable` and enabled for the
   project (`plugin_connections.capabilities_enabled` includes `searchable`).
3. For each result, uses the LLM to extract: problem, industry, product, pain point,
   buying-intent classification, and a confidence score — then checks it against existing
   `knowledge_items` (by URL) to avoid duplicating a thread it already knows about.
4. Writes new/updated `knowledge_items` rows, each publishing a `knowledge_item.created`
   domain event in the same transaction (`ARCHITECTURE.md` §7). Does **not** draft a reply
   itself — `content_agent` subscribes to that event and reacts independently; this agent
   has no reference to it.

## Reads

`projects.icp_config`, existing `knowledge_items` (dedup check).

## Writes

`knowledge_items`, `domain_events` (`knowledge_item.created`, one per new/updated item).

## Config

Per-plugin search parameters (subreddit allowlists, search terms scoped to a specific
platform) live on that plugin's `plugin_connections.config`, not here — see
`docs/decisions/0009-plugin-config-schema-dynamic-ui.md`. This agent's own config is limited
to cross-plugin behavior:

```json
{
  "min_confidence_to_save": 0.4,
  "max_results_per_platform": 25
}
```

## Notes

`min_confidence_to_save` exists because "worth writing to the knowledge base" and "worth a
human's attention" are different bars — low-confidence items are still saved (the vision
explicitly wants full institutional memory) but the Daily Brief and Content Agent should
weight by `buying_intent` and `confidence`, not just presence in the table.
