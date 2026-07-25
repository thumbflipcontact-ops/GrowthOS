# ADR 0008: Plugin-contributed content types, not a closed database enum

**Status:** Accepted — 2026-07-25

## Context

`content_items.type` was originally a native Postgres `ENUM` (`content_item_type`) listing
six fixed values tied to the plugins known at design time (`reddit_reply`,
`linkedin_message`, etc.). A design review (`docs/reviews/DESIGN_REVIEW.md` §1.2) identified
this as a direct violation of the 100+ plugin, zero-core-change requirement: any plugin whose
publishable content doesn't match one of the six existing values requires an
`ALTER TYPE ... ADD VALUE` migration against core schema — not a plugin-package change. This
would trigger well before the hundredth plugin; several already-planned plugins (Discord,
GitHub, Slack) don't cleanly fit the original six values.

## Decision

`content_items.type` becomes `text`. Valid values are the union of `content_types` declared
by currently-installed plugin manifests (ADR 0007), validated at the application layer (in
`ContentApprovalService`/the content-item creation path), not enforced by a database-level
enum constraint. Each plugin declares its own `ContentTypeSpec` list (key, max length,
publish-target shape) in its manifest — the same manifest mechanism ADR 0007 introduced for
discovery.

## Consequences

**Positive:** a new plugin can introduce new content types without any core schema
migration — consistent with ADR 0007's zero-core-change goal for the plugin surface as a
whole. The set of valid content types is always exactly "what the installed plugins declare,"
which can't drift from reality the way a manually-maintained enum could.

**Accepted trade-off:** losing database-level enforcement of valid `type` values — an invalid
type is now an application-layer validation failure, not a constraint violation the database
itself would reject. This is judged acceptable because the validation happens at the single
service-layer write path for `content_items` (`ContentApprovalService`), and the same
trade-off already applies to `knowledge_items.platform`, which was `text` from the start with
no ill effects — this decision brings `content_items.type` in line with that existing,
working pattern rather than introducing a new one.

**Not changed:** `buying_intent` remains a native Postgres enum — it's a core, cross-plugin
concept GrowthOS's own agents assign, not something plugin packages define new values for, so
a closed enum is the correct fit there and this ADR doesn't touch it (see
`docs/reviews/DESIGN_REVIEW.md` §3.5).
