# Contributing to GrowthOS

GrowthOS is currently a single-maintainer project. This document exists anyway because the
codebase is designed to outlive any one contributor's memory of why something is the way it
is — including yours, six months from now.

## Before you write code

1. Read `ARCHITECTURE.md`. If what you're about to build seems to require breaking one of
   the five guiding constraints in §2, stop and write an ADR under `docs/decisions/` before
   writing the code, not after.
2. Check `ROADMAP.md`. If the thing you want to build is listed under "Deferred," there's a
   reason — re-read it before deciding the reason no longer applies.
3. If you're adding a new agent or plugin, read `docs/agents/AGENT_ARCHITECTURE.md` or
   `docs/plugins/PLUGIN_ARCHITECTURE.md` first — both have a "how to add a new one" checklist.

## Ground rules

- **No project-specific code.** If a change only makes sense for ScoutSEO, it belongs in
  project configuration (database row / JSON config), not in `agents/`, `plugins/`, or
  `backend/`. This is enforced by convention and code review, not tooling — treat it as a
  hard rule.
- **No agent imports another agent.** Cross-agent communication happens by publishing and
  subscribing to domain events (`docs/agents/AGENT_ARCHITECTURE.md` §Communication) — never
  a direct call, never a shared in-memory reference. If you find yourself importing
  `agents.conversation_finder` from inside `agents.content_agent`, the design is wrong; add
  or adjust a subscription in `agents/content_agent/subscriptions.py` instead.
- **No agent or backend code imports a specific plugin module directly.** Always go through
  the `PluginRegistry`, and always request a capability Protocol (`Searchable`,
  `Publishable`, etc.), never a plugin by name where a capability would do. This is what
  makes "add LinkedIn support" a plugin-folder change instead of a cross-codebase change.
- **No core code lists which plugins or agents exist.** Plugins are discovered via manifest
  + entry point (`docs/plugins/PLUGIN_ARCHITECTURE.md` §Discovery); event subscribers are
  discovered by scanning installed agent packages. If you find yourself adding a plugin or
  agent name to a file outside that plugin's or agent's own package, stop — that's exactly
  the core-code-change-per-plugin problem the manifest system exists to prevent.
- **Every external-facing artifact is a `ContentItem`.** If you're writing code that causes
  something to appear on Reddit, LinkedIn, email, or anywhere else a human didn't explicitly
  click "approve" on, you're bypassing the approval state machine — don't.
- **Every discovered signal becomes a `KnowledgeItem`.** Don't let an agent's LLM call
  produce a result that only exists in a log line.

## Code style

- Python: `ruff` for linting and formatting, `mypy --strict` on `backend/` and `agents/`
  shared interfaces. Type hints are required on all public functions.
- TypeScript: `eslint` + `prettier`, strict mode on.
- Commit messages: imperative mood, one logical change per commit
  (`Add MetricsQueryable capability Protocol`, not `updates`).

## Testing expectations

See `docs/testing/TESTING.md` for the full strategy. The short version: every agent and
plugin ships with its own test suite in its own folder; nothing merges without tests for the
behavior it adds; the approval state machine has 100% branch coverage because it's the
component the entire trust model depends on.

## Adding a new agent

1. Create `agents/<name>/` with `README.md`, `config.py`, `prompts/`, `tools.py`, `agent.py`,
   `subscriptions.py`, `tests/`. Use an existing agent as the template.
2. Define the agent's config schema (pydantic) — what a project needs to configure to enable
   it.
3. Implement `run(ctx: AgentContext) -> AgentResult`. Read from the data layer and plugin
   registry only — never import another agent.
4. Declare `SUBSCRIPTIONS` in `subscriptions.py` for whatever domain events should trigger
   this agent (leave it empty for a schedule-only agent). If it needs a schedule instead of
   or in addition to subscriptions, add it to the relevant project's
   `orchestrator`-config `daily_cycle_agents` list (`agents/orchestrator/README.md`) — this
   is the *only* place any agent's name needs to appear outside its own package, and only
   for schedule-triggered agents.
5. Write tests, including one test that runs the agent against a mocked plugin registry
   end-to-end and one that verifies the subscription filter(s) accept/reject as intended.

## Adding a new plugin

1. Create `plugins/<name>/` with `manifest.py`, `README.md`, `client.py`, `plugin.py`,
   `tests/`.
2. Declare the manifest — `key`, `interface_version`, `capabilities`, `content_types`,
   `config_schema`, `auth_type` — honestly. Don't declare `publishable` if you haven't
   implemented and tested `publish()`.
3. Implement `GrowthOSPlugin` plus whichever capability Protocols
   (`Searchable`/`Publishable`/`WebhookReceivable`/`MetricsQueryable`) your manifest claims —
   see `docs/plugins/PLUGIN_ARCHITECTURE.md`.
4. Register the entry point in `pyproject.toml`
   (`[project.entry-points."growthos.plugins"]`) — **this is the only file outside the
   plugin's own package that needs an edit**, and it's plugin-package metadata, not core
   code.
5. Write tests, including the shared contract test suite
   (`plugins/_shared/tests/test_plugin_contract.py`) parameterized against your plugin — this
   is what stops "add a plugin" from becoming "add a plugin and also debug seven call sites."

## Review checklist (self-review before merging)

- [ ] Does this change touch any of the five guiding constraints in `ARCHITECTURE.md` §2? If
      yes, is there an ADR?
- [ ] Any new external-facing content path — does it go through `ContentItem` /
      `ContentApprovalService`?
- [ ] Any new discovered signal — does it become a `KnowledgeItem`?
- [ ] Any new plugin capability used — was it declared and tested?
- [ ] Tests added/updated? Docs (`docs/`, the relevant `README.md`) updated?
