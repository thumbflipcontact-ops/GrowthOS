# Plugins

Self-describing adapters between GrowthOS's domain model and external systems, discovered
automatically via manifest (no central registry to edit) and behind segmented capability
Protocols (`Searchable` / `Publishable` / `WebhookReceivable` / `MetricsQueryable`). See
[`docs/plugins/PLUGIN_ARCHITECTURE.md`](../docs/plugins/PLUGIN_ARCHITECTURE.md) for the full
design and the checklist for adding a new one — adding a plugin requires creating this kind
of package only, no edits anywhere else in the repository.

| Plugin | Capabilities | Purpose |
|---|---|---|
| [`reddit`](reddit/README.md) | searchable, publishable | Discussion discovery + reply — first plugin implemented (ADR 0005) |
| [`linkedin`](linkedin/README.md) | searchable, publishable | Discussion discovery + messaging |
| [`twitter`](twitter/README.md) | searchable, publishable | Discussion discovery + reply |
| [`gsc_community`](gsc_community/README.md) | searchable, publishable | Google Search Console forum |
| [`webmasterworld`](webmasterworld/README.md) | searchable, publishable | SEO/webmaster forum |
| [`github`](github/README.md) | searchable, publishable | Issues/discussions + contact discovery |
| [`google_analytics`](google_analytics/README.md) | metrics_queryable | Traffic/behavior signal |
| [`search_console`](search_console/README.md) | metrics_queryable | Indexing/search performance signal |
| [`email`](email/README.md) | searchable, publishable, webhook_receivable | Outreach + reply detection |
| [`crm`](crm/README.md) | searchable, publishable | External CRM sync (deferred, Phase 3) |
| [`slack`](slack/README.md) | searchable, publishable, webhook_receivable | Notifications + community monitoring |
| [`discord`](discord/README.md) | searchable, publishable, webhook_receivable | Community monitoring |

`google_analytics` and `search_console` implement `metrics_queryable` rather than
`searchable` — their data doesn't fit a free-text search shape, and forcing it through one
was a design mistake corrected in Version 2 (see
`docs/decisions/0007-plugin-discovery-and-interface-segmentation.md`).

Each plugin's own `README.md` documents its manifest, auth method, rate limits, and known
constraints.
