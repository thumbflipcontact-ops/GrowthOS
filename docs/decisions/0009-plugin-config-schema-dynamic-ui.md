# ADR 0009: Plugin-declared config schema, rendered by one generic frontend form

**Status:** Accepted — 2026-07-25

## Context

Even with ADR 0007's manifest-based discovery fixing backend extensibility, a design review
(`docs/reviews/DESIGN_REVIEW.md` §1.3) found the plugin architecture had no mechanism for a
plugin to declare *what configuration it needs* (a subreddit allowlist, OAuth scopes,
monitored channel IDs) in a form the frontend could consume generically. As designed, every
new plugin would still require someone to hand-build a bespoke connection form in
`frontend/` — meaning the 100+ plugin, zero-core-change requirement was being met on the
backend while being silently violated on the frontend, since a hand-built form per plugin is
exactly the kind of core-code change per plugin the requirement rules out.

## Decision

Every plugin manifest (ADR 0007) includes a `config_schema` — a pydantic model, exposed as
JSON Schema — describing its connection-time configuration. `plugin_connections` gains a
`config jsonb` column, validated against the owning plugin's schema on write. A
`GET /api/v1/plugins/catalog` endpoint serves the full catalog including each plugin's
`config_schema`. The frontend implements one generic component
(`DynamicConnectionForm`) that renders a connection form from any plugin's schema via a
JSON-Schema-driven form library.

## Consequences

**Positive:** adding a plugin now requires zero frontend code changes, closing the gap ADR
0007 left open. The connection experience is consistent across all plugins by construction,
rather than however each hand-built form happened to be designed.

**Accepted trade-off:** a generic schema-driven form is less polished than a hand-tuned,
plugin-specific UI could be (e.g. a custom subreddit picker with autocomplete versus a plain
text-array field). This is accepted because the alternative — bespoke UI per plugin — doesn't
scale to 100+ plugins at all, and a generic form that works is strictly better than a
beautiful form that requires a frontend engineer's time for every single plugin added.
Plugin-specific UI polish remains possible later as a targeted override for high-traffic
plugins specifically, without being required for the other 99.

**Follow-on:** `plugin_connections`'s config additionally resolves
`docs/reviews/DESIGN_REVIEW.md` §1.6 — plugin-specific settings (e.g. Reddit's subreddit
list) now live on the connection they belong to, instead of being duplicated into every
agent config that happens to use that plugin.
