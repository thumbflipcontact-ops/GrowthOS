# Competitor Watch

**Phase:** 2 · **Produces content:** no · **Trigger:** schedule
**Plugins used:** any `Searchable` plugin that can surface competitor activity — website
content (via a generic web-read plugin), `twitter`, `github` (for competitors with public
repos/changelogs)

## Purpose

Tracks what named competitors are doing — pricing changes, new features, published content —
and answers "what are competitors doing" in the Daily Brief.

## How it works

1. For each `competitors` row, checks configured sources (competitor's pricing page, blog,
   changelog, social accounts) for changes since the last run.
2. Summarizes any detected change with the LLM and writes a `competitor_observations` row.
3. Flags observations that are unusually significant (e.g. a pricing change) with higher
   priority in its run summary, which the orchestrator surfaces prominently in the Daily
   Brief.

## Reads

`competitors`, prior `competitor_observations` (diff baseline).

## Writes

`competitor_observations`, occasionally proposes new `competitors` rows for human
confirmation when it notices a company mentioned repeatedly in `knowledge_items` alongside
your product (competitive mentions surfaced organically by Conversation Finder).

## Config

```json
{
  "check_frequency_hours": 24,
  "observation_types": ["pricing_change", "new_feature", "content_published"]
}
```

## Notes

Competitor Watch reads, it never engages — it never requests `Publishable` from the plugin
registry for any connection, which is enforced structurally (`docs/plugins/PLUGIN_ARCHITECTURE.md`),
not just by convention.
