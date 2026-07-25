# Plugin: dummy (Phase 1 test fixture — not a real plugin)

**This is not a real integration.** It exists solely to prove, end-to-end, that the plugin
discovery and registry mechanism described in `docs/plugins/PLUGIN_ARCHITECTURE.md` actually
works — manifest declaration, `growthos.plugins` entry-point discovery, capability-Protocol
structural checks — before any real plugin (Reddit, first per ADR 0005) is implemented. This
is exactly the "trivial hello world plugin" exit check specified in
`docs/architecture/archive/MIGRATION_V1_TO_V2.md` Step 2.

It makes no network calls, declares `searchable` only, and is covered by
`backend/tests/integration/test_plugin_catalog_and_registry.py` (the discovery/registry
mechanism, from the core side) and its own `tests/test_contract.py` (this plugin honoring its
own manifest, via the shared contract suite — `plugins/_shared/tests/test_plugin_contract.py`).
Run just this plugin's tests from the repo root: `backend/.venv/Scripts/python -m pytest
plugins/dummy/tests -p no:cov` (Windows) or `backend/.venv/bin/python -m pytest
plugins/dummy/tests -p no:cov` (macOS/Linux) — see the root `pyproject.toml` for why this
works without `cd`-ing into `backend/`.

Do not treat this as a template to copy for a real plugin without reading
`docs/plugins/PLUGIN_ARCHITECTURE.md` §"How to add a new plugin" — this fixture skips
anything a real plugin needs (real auth, a real client, and tests against real external
behavior — its own contract test only proves it honors its manifest, not that `search()`
actually works against Reddit or wherever).
