# Customer Finder

**Phase:** 2 · **Produces content:** no · **Trigger:** schedule
**Plugins used:** `Searchable` plugins with directory data (e.g. `github`, future
firmographic data plugins) *and* `MetricsQueryable` plugins (`search_console`,
`google_analytics`) queried for existing high-intent site visitors via
`query_metrics()` — two different capability calls for two different kinds of signal, not
one uniform "read" call.

## Purpose

Finds companies and contacts matching the project's ideal customer profile. Answers "who
should I talk to today" and "which companies match my ICP" together with Outreach Assistant,
which prioritizes what this agent finds.

## How it works

1. Uses `projects.icp_config` (industry, company size, signals) to search `Searchable`
   plugins for candidate companies, and calls `query_metrics()` on connected
   `MetricsQueryable` plugins (e.g. Search Console/GA) for existing-visitor signal.
2. Scores each candidate against the ICP config, producing `icp_score`.
3. Writes/updates `companies`, and where a specific person is identifiable (e.g. a GitHub
   contributor, a forum poster with a company-affiliated profile), writes `contacts` linked
   to that company.

## Reads

`projects.icp_config`, existing `companies` (dedup by domain).

## Writes

`companies`, `contacts`.

## Config

```json
{
  "platforms": ["github"],
  "icp_overrides": {},
  "min_icp_score_to_save": 0.5
}
```

## Notes

Deliberately does not draft outreach — that's `content_agent`, triggered by
`outreach_assistant` flagging a contact as ready. Keeping "find" and "reach out to" separate
agents means you can run Customer Finder continuously to build a pipeline without it ever
being the thing that decides to contact someone.
