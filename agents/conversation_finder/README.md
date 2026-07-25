# Conversation Finder

**Phase:** 2A (implemented — see docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md)
· **Produces content:** no (produces knowledge, which a future content-drafting agent
reacts to) · **Trigger:** schedule (it originates a discovery cycle — nothing upstream to
subscribe to; see `subscriptions.py`)
**Plugins used:** any plugin implementing `Searchable`, e.g. `reddit`, `linkedin`, `twitter`,
`gsc_community`, `webmasterworld` — not `search_console`/`google_analytics`, which implement
`MetricsQueryable` instead (see `docs/plugins/PLUGIN_ARCHITECTURE.md`)

## Purpose

Searches every platform a project has connected for discussions matching that project's
configured search terms, ranks each result with a deterministic relevance score, and converts
anything above a configurable threshold into a structured `knowledge_items` row. This is the
agent that answers "which online discussions are worth a closer look."

## How it works

1. Builds the search query from this agent's own `keywords` config (falling back to
   `project.icp_config["keywords"]` if empty — see `agent.py`'s `_effective_terms()`) and
   `lookback_hours` (recency).
2. Calls `search()` on every connected plugin implementing `Searchable` and enabled for the
   project (`plugin_connections.capabilities_enabled` includes `searchable`) — resolved via
   `PluginRegistry.all_with_capability(Searchable)`, never a hardcoded plugin name. One
   plugin raising from `search()` is logged and skipped; it never fails the whole run (see
   `plugin_registry.py`'s own resilience contract for `all_with_capability`, which this
   mirrors one level up).
3. Scores each result with a deterministic, keyword-based relevance score (`ranking.py`) —
   see §Ranking below.
4. Deduplicates within the run (by URL) and against existing `knowledge_items` (also by URL,
   via `ctx.knowledge_base.upsert_discovery` — a re-discovered thread refreshes its
   tags/confidence in place rather than raising the unique constraint or duplicating a row).
5. Writes rows scoring at or above `min_score_to_save`, each publishing a
   `knowledge_item.created` domain event in the same transaction (only for genuinely new
   rows — refreshing an existing one is not a new fact worth another event). Does **not**
   draft a reply itself — a future content-drafting agent would subscribe to that event and
   react independently; this agent has no reference to it.

## Ranking

`ranking.py`'s `score_result()` computes a score in `[0, 1]`: the weighted fraction of
configured search terms that appear in a result's title and/or body, where a title match
counts for more (0.7) than a body-only match (0.3). This is deliberately platform-agnostic —
it only reads `PluginResult.title`/`.body`, which every `Searchable` plugin returns regardless
of platform, never a `platform_metadata` key (opaque and plugin-specific, see
`plugins/_shared/base.py`). Matched terms (lowercased, deduplicated) become the item's `tags`.

## What Phase 2A does not do

**No LLM integration** (explicitly out of scope, see `ROADMAP.md`). This agent does not call
an LLM, so it does not populate `knowledge_items.problem`/`industry`/`product`/`pain_point`/
`buying_intent`/`suggested_reply`/`suggested_article`/`suggested_product_idea` — those stay
at the model's schema defaults (`buying_intent="none"`, everything else `null`) until a
future enrichment pass fills them in. `confidence` here means "how well this result matches
the configured search terms" (a deterministic score — see `ranking.py`), not an LLM's
judgment of buying intent; treat it accordingly when reading `knowledge_items` written by
this agent. See `docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md`'s "Scoping
decisions" section for the full reasoning.

## Reads

`project.icp_config` (fallback search terms only), existing `knowledge_items` (dedup check
by URL, via `ctx.knowledge_base`).

## Writes

`knowledge_items` (new rows or in-place refreshes), `domain_events`
(`knowledge_item.created`, one per newly created item).

## Config

```json
{
  "keywords": ["crawl budget", "core web vitals", "canonical tags"],
  "lookback_hours": 168,
  "max_results_per_platform": 25,
  "min_score_to_save": 0.2
}
```

Per-plugin search parameters (subreddit allowlists, etc.) live on that plugin's own
`plugin_connections.config`, not here — see
`docs/decisions/0009-plugin-config-schema-dynamic-ui.md` and
`plugins/reddit/manifest.py`'s `RedditConnectionConfig`. This agent's own config is limited
to cross-plugin behavior. `min_score_to_save` is deliberately low by default —
`docs/knowledge-base/KNOWLEDGE_BASE.md`: "worth writing to the knowledge base" and "worth a
human's attention" are different bars; a low-scoring item is still saved, just expected to be
weighted down by whatever later reads `confidence`.

Set this config via `PUT /api/v1/projects/{project_id}/agent-configs/conversation_finder`
(also where `schedule_cron` is set — see `docs/api/API_DESIGN.md`); trigger an on-demand run
via `POST .../agent-configs/conversation_finder/runs/trigger`; read run history via
`GET .../agent-configs/conversation_finder/runs`; read discovered items via
`GET /api/v1/projects/{project_id}/knowledge-items`.
