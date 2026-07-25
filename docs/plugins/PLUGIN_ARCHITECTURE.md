# Plugin Architecture

**Version 2** — rewritten following the Principal Engineer design review
(`docs/reviews/DESIGN_REVIEW.md` §1) that found the original design didn't actually meet
GrowthOS's stated requirement: support 100+ plugins over its lifetime, each addable by
creating a plugin package and configuration, with zero changes to core code. Everything below
is written to satisfy that requirement mechanically. See `docs/decisions/0007-plugin-discovery-and-interface-segmentation.md`,
`0008-plugin-contributed-content-types.md`, and `0009-plugin-config-schema-dynamic-ui.md`.

## What a plugin is

A plugin is a self-describing adapter between GrowthOS's domain model and one external
system — Reddit, LinkedIn, Google Analytics, Slack, and so on. Plugins are the only code in
GrowthOS allowed to make network calls to external services. Agents never call an external
API directly; they go through the plugin registry, and the registry only ever hands out
plugin instances typed to the specific capability the caller asked for.

## The manifest — how a plugin describes itself

Every plugin package ships a `manifest.py`:

```python
# plugins/reddit/manifest.py
from growthos.plugins import PluginManifest, ContentTypeSpec

MANIFEST = PluginManifest(
    key="reddit",
    interface_version="1.0",
    capabilities=["searchable", "publishable"],
    content_types=[
        ContentTypeSpec(key="reddit_reply", max_length=10_000, publish_target="thread"),
    ],
    config_schema=RedditConnectionConfig,      # a pydantic model → JSON Schema
    auth_type="oauth2",
)
```

This one object is the complete, machine-readable description of what the plugin is, what it
can do, what it can publish, and what configuration it needs to connect — everything the core
system, the API, and the frontend need to know about it, without importing any of the
plugin's actual client code.

## Discovery — a scanner, never a list

At process startup, the core `PluginCatalog` discovers installed plugins via Python entry
points, declared in each plugin's `pyproject.toml`:

```toml
[project.entry-points."growthos.plugins"]
reddit = "plugins.reddit.manifest:MANIFEST"
```

The catalog scans every registered entry point, validates each manifest's
`interface_version` against the range the running core supports (failing loudly at startup,
not silently at first use, if a plugin is incompatible), and refreshes the `plugin_catalog`
database table. **There is no file anywhere in `backend/` that lists plugin names.** Adding a
plugin is: create `plugins/<name>/` with a manifest and an implementation, install the
package, restart the process. Nothing else changes.

## The capability contract — segmented, not one fat interface

The single most important lesson from the design review: a plugin's capabilities are
distinct Protocols, not a runtime enum gating one giant interface. This matters because a
Reddit-shaped "search for discussion" and a Google-Analytics-shaped "query a metrics report"
are genuinely different operations that shouldn't be forced through the same method
signature — attempting that already produced awkward, admitted-in-the-README mappings for
`google_analytics` and `search_console` before this rewrite.

```python
# plugins/_shared/base.py

@dataclass
class PluginQuery:
    project_id: UUID
    terms: list[str]
    since: datetime | None = None
    limit: int = 25

@dataclass
class PluginResult:
    url: str
    title: str | None
    body: str
    author: str | None
    platform_metadata: dict

@dataclass
class MetricsQuerySpec:
    project_id: UUID
    metric_keys: list[str]
    date_range: tuple[date, date]
    dimensions: list[str] = field(default_factory=list)

@dataclass
class MetricsResult:
    rows: list[dict]              # shape declared by the plugin's own documentation
    metric_keys: list[str]

@dataclass
class PublishResult:
    success: bool
    published_url: str | None
    error: str | None

class Searchable(Protocol):
    async def search(self, query: PluginQuery) -> list[PluginResult]: ...

class Publishable(Protocol):
    async def publish(self, item: "ContentItem") -> PublishResult: ...

class WebhookReceivable(Protocol):
    async def handle_webhook(self, payload: dict) -> None: ...

class MetricsQueryable(Protocol):
    async def query_metrics(self, spec: MetricsQuerySpec) -> MetricsResult: ...

class GrowthOSPlugin(Protocol):
    manifest: "PluginManifest"
    async def health_check(self) -> bool: ...
```

A plugin implements `GrowthOSPlugin` plus whichever of the four capability Protocols
describe what it actually does. Reddit implements `Searchable` + `Publishable`. Google
Analytics implements `MetricsQueryable` only. A community-monitoring Discord plugin
implements all four.

## The registry

```python
class PluginRegistry:
    def __init__(self, project: Project, connections: list[PluginConnection]): ...

    def get(self, key: str, required: type[Searchable | Publishable | WebhookReceivable | MetricsQueryable]) -> Any:
        """Returns a plugin instance scoped to this project. Raises if the plugin isn't
        connected, isn't enabled for `required` at the project level
        (plugin_connections.capabilities_enabled), or doesn't structurally implement
        `required` — checked by isinstance against the Protocol, not a string in an enum."""

    def all_with_capability(self, cap: type) -> list[Any]:
        """Used by agents like conversation_finder that want to query everything connected
        and Searchable, without knowing plugin names in advance."""
```

Agents ask the registry for a *capability type*, not a plugin name, wherever possible — this
is what lets `conversation_finder`'s code stay unchanged when a project connects a 50th
`Searchable` plugin.

**Two independent gates on every publish call:** the plugin's own declared capability
(code-level, whether it implements `Publishable` at all) and the project's
`plugin_connections.capabilities_enabled` (data-level, whether the user has turned publishing
on for this specific connection). Both must allow it. A plugin capable of publishing can still
be configured read-only for a given project.

## Plugin-contributed content types

`content_items.type` is `text`, validated against the union of `content_types` declared by
every currently-installed plugin's manifest — never a fixed database enum. A new plugin
introducing a new kind of publishable content (a Discord thread reply, a GitHub issue
comment) requires no core schema migration; it just declares its `ContentTypeSpec` in its own
manifest. See `docs/database/SCHEMA.md` for the full reasoning and the deliberate contrast
with `buying_intent`, which *is* a core enum because it's a core-owned taxonomy, not a
plugin-contributed one.

## Plugin-declared configuration and the generic connection UI

Every plugin's `config_schema` (a pydantic model) is exposed as JSON Schema via
`GET /api/v1/plugins/catalog`. `plugin_connections.config jsonb` holds each connection's
actual settings (a subreddit allowlist, OAuth scopes, monitored channel IDs), validated
against that schema on write. The frontend implements **one** generic
`DynamicConnectionForm` component that renders any plugin's connection form from its schema.
This is what makes "adding a plugin" a zero-frontend-code-change operation, not just a
zero-backend-code-change one — see `docs/decisions/0009-plugin-config-schema-dynamic-ui.md`.

## Credentials

`plugin_connections.credentials_encrypted` is protected by envelope encryption — a rotatable
master key wraps a unique data key per connection, and the data key encrypts the actual
credential. See `docs/security/SECURITY.md` and
`docs/decisions/0010-envelope-encryption-for-credentials.md`. Plugin code receives decrypted
credentials only inside the request-scoped plugin instance the registry constructs; nothing
outside `plugins/` ever handles raw credentials.

## Rate limiting & backoff

Each plugin is responsible for respecting its own external API's rate limits, via a shared
`plugins/_shared/rate_limit.py` helper backed by Redis (token bucket per `plugin_key` +
`project_id`). A throttled plugin returns fewer/no results and logs a warning rather than
raising, so one rate-limited plugin never fails an entire agent run that also queries other
plugins.

## Webhooks and events

A `WebhookReceivable` plugin's `handle_webhook()` writes its resulting row (e.g. a
`knowledge_item` from a Slack mention) and that row's domain event
(`knowledge_item.created`) in a single transaction — exactly like a scheduled agent's write
does. This is what gives webhook-triggered discovery a real, immediate reactivity path
instead of sitting inert until the next scheduled cycle. See `ARCHITECTURE.md` §7 and
`docs/agents/AGENT_ARCHITECTURE.md`.

## Interface versioning

Every manifest declares `interface_version`. The running core supports a range of versions;
a plugin outside that range fails at startup, not at first invocation. This exists because,
over a 100+-plugin, multi-year lifetime, the `GrowthOSPlugin`/capability Protocol contract
will eventually need a breaking change, and there must be a way to know which installed
plugins were written against which version rather than discovering it as a runtime failure.
The deprecation policy (how long an old interface version stays supported after a new one
ships) should be documented here once the first breaking change is actually being planned —
not speculatively now.

## Trust model

Plugins execute as in-process Python code with full process access — they can read
environment variables, and nothing structurally prevents one plugin's code from reaching
into another's memory during concurrent execution. **The current design assumes every
installed plugin is first-party, code-reviewed code.** This is a reasonable trust model for a
handful of plugins written by the GrowthOS maintainer. It is not a safe trust model for
accepting plugins from unknown authors — a real isolation boundary (subprocess execution,
capability-restricted sandboxing) is a prerequisite before that ever happens. This is stated
explicitly here so it's a deliberate, visible limit rather than a gap discovered during an
incident. See `docs/security/SECURITY.md` and `docs/architecture/LOCKED_DECISIONS.md` §2.

## The read vs. read+write plugin roster

| Plugin | Capabilities | Notes |
|---|---|---|
| `reddit` | searchable, publishable | First plugin implemented — see ADR 0005 |
| `linkedin` | searchable, publishable | |
| `twitter` | searchable, publishable | |
| `gsc_community` | searchable, publishable | No public API; scraping-based |
| `webmasterworld` | searchable, publishable | No public API; scraping-based |
| `github` | searchable, publishable | |
| `google_analytics` | metrics_queryable | Signal source only — see below |
| `search_console` | metrics_queryable | Signal source only |
| `email` | searchable, publishable, webhook_receivable | |
| `crm` | searchable, publishable | Deferred to Phase 3 |
| `slack` | searchable, publishable, webhook_receivable | |
| `discord` | searchable, publishable, webhook_receivable | |

`google_analytics` and `search_console` now implement `MetricsQueryable` rather than being
forced through `Searchable` — this is the direct fix for the "not a natural fit" caveat both
plugins' own READMEs carried under the original design.

## How to add a new plugin

1. Create `plugins/<name>/` — `manifest.py`, `client.py`, `plugin.py` (implementing
   `GrowthOSPlugin` plus whichever capability Protocols apply), `README.md`, `tests/`.
2. Declare capabilities, content types, and `config_schema` honestly in the manifest — don't
   declare `publishable` if you haven't implemented and tested `publish()`.
3. Register the entry point in `pyproject.toml`.
4. Write tests, including the shared contract test suite
   (`plugins/_shared/tests/test_plugin_contract.py`) run against your plugin, parameterized —
   this verifies your plugin actually honors whichever Protocols it claims to implement.
5. Install the package and restart. **No other file in the repository needs to change.**
