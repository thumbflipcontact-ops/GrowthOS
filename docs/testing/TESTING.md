# Testing Strategy

## Layers

| Layer | Location | What it covers | Runs against |
|---|---|---|---|
| Unit | `agents/<name>/tests/`, `plugins/<name>/tests/`, `backend/tests/unit/` | Single function/class behavior | Nothing external — pure logic, mocks |
| Contract | `plugins/_shared/tests/test_plugin_contract.py`, run against every plugin | Every plugin structurally honors the capability Protocols (`Searchable`/`Publishable`/`WebhookReceivable`/`MetricsQueryable`) its manifest declares | Mocked external API, real plugin code |
| Service/integration | `backend/tests/integration/` | Service-layer logic against a real database | Real Postgres (test container), mocked external calls |
| End-to-end | `tests/e2e/` | Full request flows through the API | Full stack in Docker Compose, mocked plugin external calls only |

## The one component with a stricter bar

`ContentApprovalService` (the approval state machine, `ARCHITECTURE.md` §8) requires 100%
branch coverage, including every illegal-transition case
(`pending_review → published` directly, `approved → approved`, reviewing an already-reviewed
item, etc.), each asserting `InvalidStateTransition` is raised and no database write occurs.
This is the one place in the codebase where "well-tested" is a project requirement, not just
good practice — it's the component the entire trust model in `ARCHITECTURE.md` depends on.

## Agent tests

Every agent ships `tests/test_agent.py` that runs its full `run(ctx)` against:
- A mocked `PluginRegistry` returning fixture data (recorded or hand-written
  `PluginResult`s).
- A mocked or cassette-recorded `LLMProvider` response (see below) — never a live LLM call in
  CI, for cost, speed, and determinism.
- Assertions on the resulting `AgentResult` and the database rows actually written (using the
  integration-layer test database).

## LLM call testing

LLM calls are tested via recorded cassettes (VCR-style: record a real response once during
development against a real API key, replay it in CI) for agents whose behavior depends on
realistic model output, and via a simple stub `LLMProvider` returning fixed structured output
for tests that only care about what the agent *does* with a given LLM response, not whether
the prompt produces a good one. Prompt quality itself is evaluated separately and manually
during agent development — this is a judgment call, not something a unit test suite
verifies well; see `docs/agents/AGENT_ARCHITECTURE.md` for where prompts live.

## Plugin contract tests

A shared test suite (`plugins/_shared/tests/test_plugin_contract.py`) runs against every
registered plugin, parameterized, verifying:
- the manifest's declared `capabilities` match what's actually implemented (a plugin
  declaring `publishable` must structurally implement `Publishable`, with a working, tested
  `publish()`).
- `search()` returns well-formed `PluginResult`s, or an empty list, never raises for a valid
  query (errors go through `PluginError`, not arbitrary exceptions).
- `publish()` raises `CapabilityNotSupported` if `Publishable` isn't implemented, verified
  even for plugins where it IS implemented (both branches).

This is what makes "add a new plugin" a change with an automatic quality bar, per
`CONTRIBUTING.md`.

## Database tests

Integration tests run against a real Postgres instance (via `testcontainers` or a dedicated
CI Postgres service), not SQLite or a mocked ORM — the schema uses Postgres-specific features
(enums, `pgvector`, JSONB, array columns, check constraints) that a lighter substitute
wouldn't exercise faithfully, and the `review_fields_consistent` check constraint in
particular needs to be tested against the real database to confirm it actually rejects
invalid writes.

## Frontend testing

Component tests (Vitest + React Testing Library) for the Approval Inbox and Morning Brief
views specifically — these are the highest-consequence UI surfaces (approving real content).
Broader end-to-end coverage (Playwright) for the full approve/reject flow against a running
backend, as part of `tests/e2e/`.

## CI gates

Every PR runs: lint (ruff, mypy, eslint), unit + contract + integration tests, and the
frontend test suite. End-to-end tests run on merge to main (slower, full-stack) rather than
on every PR, to keep PR feedback fast — see `docs/deployment/DEPLOYMENT.md` for the CI
pipeline itself.
