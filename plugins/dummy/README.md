# Plugin: dummy (Phase 1 test fixture — not a real plugin)

**This is not a real integration.** It exists solely to prove, end-to-end, that the plugin
discovery and registry mechanism described in `docs/plugins/PLUGIN_ARCHITECTURE.md` actually
works — manifest declaration, `growthos.plugins` entry-point discovery, capability-Protocol
structural checks — before any real plugin (Reddit, first per ADR 0005) is implemented. This
is exactly the "trivial hello world plugin" exit check specified in
`docs/architecture/archive/MIGRATION_V1_TO_V2.md` Step 2.

It makes no network calls, declares `searchable` only, and is covered by
`backend/tests/integration/test_plugin_registry.py`.

Do not treat this as a template to copy for a real plugin without reading
`docs/plugins/PLUGIN_ARCHITECTURE.md` §"How to add a new plugin" — this fixture skips
anything a real plugin needs (real auth, a real client, real tests against real behavior).
