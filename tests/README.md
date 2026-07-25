# Cross-cutting tests

Integration and end-to-end tests that span more than one package — a single agent's or
plugin's own tests live alongside it (`agents/<name>/tests/`, `plugins/<name>/tests/`), not
here. See `docs/testing/TESTING.md` for the full strategy.

```
tests/
├── e2e/            Full-stack flows through the API against a running Docker Compose stack
│                    (e.g. "agent discovers a thread → drafts a reply → human approves →
│                    plugin publish is invoked", with plugin external calls mocked)
└── fixtures/        Shared fixtures (sample PluginResults, sample ICP configs, etc.) used
                      across backend/, agents/, and plugins/ test suites
```

## Status

Scaffolding only. The first end-to-end test to write, once Phase 1 is implemented, is the
scenario above — it's the smallest test that proves the entire trust model
(`ARCHITECTURE.md` §8) actually holds, not just in each unit's isolation.
