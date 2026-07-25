# ADR 0007: Manifest-based plugin discovery and segmented capability interfaces

**Status:** Accepted — 2026-07-25

## Context

GrowthOS has an explicit, non-negotiable requirement: support 100+ plugins over its
lifetime, where adding one requires creating a plugin package and configuration only — no
core code changes. A design review (`docs/reviews/DESIGN_REVIEW.md` §1) found the original
plugin architecture violated this in two independent ways: the `PluginRegistry` was
described as a hand-maintained list requiring a core-code edit per plugin, and `BasePlugin`
was a single Protocol with a runtime capability enum, forcing heterogeneous plugin types
(discussion search, metrics/analytics queries, directory lookups) through one method
signature — already visibly awkward at 12 plugins (`google_analytics` and `search_console`'s
own READMEs note `search()` doesn't really fit their model).

## Decision

**Discovery:** every plugin ships a manifest (`PluginManifest`: key, interface version,
capabilities, content types, config schema, auth type) declared via a Python entry point.
The core `PluginCatalog` scans installed packages for manifests at startup — it is a
*scanner*, never a list requiring an edit. A plugin whose declared `interface_version` is
unsupported by the running core fails loudly at startup.

**Interface segmentation:** replace the single `BasePlugin` Protocol with capability-specific
Protocols — `Searchable`, `Publishable`, `WebhookReceivable`, and a new `MetricsQueryable` for
analytics/reporting-shaped plugins. A plugin implements only the Protocols that describe what
it actually does. The registry's capability check becomes a structural type check, not a
runtime enum-membership check.

See `ARCHITECTURE.md` §5 for the full design (merged from the original V2 proposal, archived
at `docs/architecture/archive/ARCHITECTURE_V2_PROPOSAL.md`).

## Consequences

**Positive:** adding a plugin is mechanically zero-core-code-change, meeting the stated
requirement rather than approximating it. `mypy` can now actually verify capability claims
at the type level. Analytics-shaped plugins get an interface that fits what they do instead
of an awkward mapping onto free-text search.

**Accepted trade-off:** four Protocols to understand instead of one — marginally more
surface area for a plugin author to learn. Judged worthwhile because the alternative (one
interface that fits nothing well as plugin diversity grows) was already failing at 12
plugins and would only get worse at 100+.

**Follow-on requirement:** `CONTRIBUTING.md`'s plugin checklist and
`docs/plugins/PLUGIN_ARCHITECTURE.md` must be rewritten to match — the old "register in the
registry" instruction is actively wrong under this decision and would mislead a contributor
following it literally.
