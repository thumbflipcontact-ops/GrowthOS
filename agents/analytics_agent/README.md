# Analytics Agent

**Phase:** 3 (deferred) · **Plugins used (planned):** `google_analytics`, `search_console`

## Purpose (planned)

Surfaces patterns across GrowthOS's own operational data and connected analytics — which
content types actually drive traffic/signups, which channels produce the highest-outcome
`knowledge_items`, where the ICP definition itself might be wrong based on who's actually
converting.

## Why this is deferred

This agent's entire value is comparative: "content type A outperforms content type B," "this
channel converts better than that one." Before Phase 1–2 have been running long enough to
accumulate real `content_items` outcomes and `knowledge_items` volume, there is nothing for
this agent to find patterns *in* — building it now means designing its logic against
imagined data instead of real distributions. See `ROADMAP.md` §Deferred.

## What exists today

Nothing — this README is a placeholder for design intent, not an implementation. When Phase
3 starts, this document should be replaced with the same structure as the other agent
READMEs (How it works / Reads / Writes / Config) once real usage data informs what's actually
worth measuring.
