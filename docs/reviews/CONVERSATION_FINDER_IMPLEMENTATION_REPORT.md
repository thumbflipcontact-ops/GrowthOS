# Conversation Finder Implementation Report (Phase 2A)

**Date:** 2026-07-25
**Scope:** implement Phase 2A of the Reddit Discovery → Conversation Selection → AI Draft
Generation → Human Review → Approval → Publish → Audit Trail workflow — the Conversation
Finder service: search, ranking/scoring, deduplication, persistence into the Knowledge Base,
domain events, background job scheduling, and API endpoints to trigger discovery and
retrieve results. Explicitly excluded per this task's instructions: AI reply generation, LLM
integration, Content Agent, the approval workflow, publishing, any UI.

---

## 1. Conversation Finder Implementation Report

### What was built

```
agents/conversation_finder/
├── config.py           ConversationFinderConfig — keywords, lookback_hours,
│                          max_results_per_platform, min_score_to_save
├── ranking.py            score_result() — deterministic keyword-relevance scoring
├── agent.py               ConversationFinderAgent — run(ctx), AGENT singleton
├── subscriptions.py        AGENT_SUBSCRIPTIONS — empty tuple (schedule-only)
├── pyproject.toml           Entry point + packaging (same pattern as plugins/reddit/)
├── README.md                 Rewritten — real implementation, not a forward-looking spec
└── tests/
    ├── test_config.py          Config schema validation (7 tests)
    ├── test_ranking.py          Scoring logic (9 tests)
    ├── test_subscriptions.py     Schedule-only contract (2 tests)
    └── test_agent.py              End-to-end run() against mocked collaborators (9 tests)

backend/app/
├── core/agent_registry.py            load_agent(key) — the agent-side mirror of
│                                        plugin_registry.py's import-by-key convention
├── services/knowledge_base.py         KnowledgeBaseClient — AgentContext.knowledge_base's
│                                        first concrete implementation
├── services/agent_config.py            AgentConfigService — create/update agent_configs,
│                                        validated against the target agent's config_schema
├── repositories/knowledge_repository.py  KnowledgeItemRepository
├── repositories/agent_repository.py       + get_by_project_and_key, list_by_project_and_key
├── jobs/agent_runs.py                      run_scheduled_agent — real body (was a placeholder)
├── api/deps.py                              + get_arq_redis (lazy Arq pool dependency)
├── api/v1/agent_configs.py                   agent-configs CRUD + runs/trigger + runs list
├── api/v1/knowledge_items.py                  knowledge-items list (read-only)
└── schemas/agent.py, schemas/knowledge.py       Request/response models
```

**No database migration.** `knowledge_items`, `agent_configs`, and `agent_runs` were all
already part of the Phase 0/1 schema (`database/schema.sql`) — built ahead of any agent that
would populate them, per `ROADMAP.md`'s step ordering. Phase 2A is the first thing to write
to two of those three tables for real.

### How discovery flows, end to end

1. A cron tick (`app/scheduler.py`, unchanged) or an on-demand
   `POST .../agent-configs/conversation_finder/runs/trigger` call enqueues the existing
   `run_scheduled_agent` Arq job with an `agent_config_id` — one job body, one code path, for
   both triggers.
2. `run_scheduled_agent` (now real, `backend/app/jobs/agent_runs.py`) loads the
   `agent_configs` row, writes an `agent_runs` row (`status=running`), resolves the agent via
   `app/core/agent_registry.load_agent("conversation_finder")`, builds a real `AgentContext`
   (a `PluginRegistry` scoped to the project's connections, the concrete
   `KnowledgeBaseClient`, the transactional `EventPublisher`), and calls `agent.run(ctx)`.
3. `ConversationFinderAgent.run()` builds a `PluginQuery` from its own config (or the
   project's `icp_config["keywords"]` as a fallback), calls `search()` on every connected,
   `searchable`-enabled plugin via `ctx.plugins.all_with_capability(Searchable)` — never a
   named plugin — scores each result with `ranking.py`'s deterministic keyword-relevance
   function, deduplicates by URL (within the run, and against existing `knowledge_items` via
   `ctx.knowledge_base.upsert_discovery`), and writes survivors above `min_score_to_save`.
4. Each genuinely new row publishes a `knowledge_item.created` domain event in the same
   transaction (`ctx.events.publish(...)`, flushed, not committed — the job owns the
   transaction boundary, per `app/core/events.py`'s documented contract).
5. The job records `succeeded`/`failed` on the `agent_runs` row and commits. A failure
   re-raises after the row is written, so Arq's existing `max_tries=3` retry policy still
   applies — each attempt gets its own `agent_runs` row, which is correct: every attempt
   genuinely happened.

### Scoping decisions (read before assuming this agent's output means what the original spec implied)

**No LLM integration — by instruction, and it shows in the data.** The pre-existing
`agents/conversation_finder/README.md` spec (written before this task, describing the full
target design) assumed an LLM call per result to extract `problem`/`industry`/`product`/
`pain_point`/`buying_intent` and draft `suggested_reply`/`suggested_article`/
`suggested_product_idea`. This task's instructions explicitly excluded "AI reply generation"
and "LLM integration," and no LLM provider client exists yet in this codebase at all (`core/
config.py` has the settings plumbing; `AgentContext.llm` is still typed `object` — see
`docs/decisions/0004-llm-provider-abstraction.md`). So Conversation Finder writes every
`knowledge_items` row with those seven fields at their **schema defaults**
(`buying_intent="none"`, everything else `null`) — it cannot honestly do otherwise without an
LLM. What it *does* populate: `platform`, `url`, `discovered_at`, `tags` (the search terms
that actually matched), and `confidence` — reinterpreted as a **deterministic keyword-
relevance score** (see `ranking.py`), not an LLM's judgment of buying intent. This is
documented at three levels so it can't be missed later: `agents/conversation_finder/
README.md` §"What Phase 2A does not do", `docs/knowledge-base/KNOWLEDGE_BASE.md`'s new
"Phase 2A note", and here.

**Ranking is platform-agnostic by construction, not by discipline.** `score_result()` only
reads `PluginResult.title`/`.body` — fields every `Searchable` plugin returns regardless of
platform — and weights a title match (0.7) over a body-only match (0.3) for each configured
search term. It never reads `platform_metadata` (Reddit's `score`/`num_comments`, opaque and
plugin-specific per `plugins/_shared/base.py`), so no Reddit-specific signal leaked into core
ranking logic even implicitly. `platform` itself (needed for `knowledge_items.platform`) comes
from `plugin.manifest.key` — a field every plugin instance already carries — not from any
per-plugin branch.

**Subreddit-style per-plugin search scoping was deliberately not duplicated here.** Requirement
3 asks for "subreddits" as a configurable search-strategy dimension. That already exists —
`plugins/reddit/manifest.py`'s `RedditConnectionConfig.subreddits`, on the plugin connection,
per `docs/decisions/0009-plugin-config-schema-dynamic-ui.md`. `ConversationFinderConfig` only
holds cross-plugin knobs (`keywords`, `lookback_hours`, `max_results_per_platform`,
`min_score_to_save`); duplicating subreddit config at the agent level would mean two sources
of truth for the same setting and would require this agent to know Reddit-specific config
shape — exactly what "no Reddit-specific logic in the platform" rules out.

**One small, generic platform extension, mirroring an existing asymmetry, not a new one.**
`app/core/agent_registry.py` is new: given an `agent_key`, it imports
`agents.<agent_key>.agent` and returns its module-level `AGENT` singleton. This mirrors
`app/core/plugin_registry.py`'s `_load_plugin_instance` — entry points (`growthos.agents`,
`growthos.plugins`) are for *discovery* (what's installed); a plain import-by-known-key
convention is for *loading something you already know you need*, the same split that already
existed for plugins. No new architectural pattern, no ADR needed.

**`AgentContext` gained one field, additively.** `agent_run_id: uuid.UUID | None = None` —
so an agent can stamp `knowledge_items.source_agent_run_id` (a column that already existed in
the Phase 0 schema for exactly this purpose). Defaults to `None`; every existing (hypothetical)
caller is unaffected. `knowledge_base: object` was tightened to the concrete
`KnowledgeBaseClient` — this was explicitly flagged in `agents/_shared/base.py`'s own
docstring as something "Phase 2 tightens," not a deviation.

**The Arq connection pool is lazy, not eager, to avoid a hidden Redis dependency on every
route.** `app/api/deps.py`'s new `get_arq_redis` creates and caches one `ArqRedis` pool on
first use, not at app startup — unlike `plugin_catalog`. Adding it eagerly (mirroring
`plugin_catalog`'s pattern) would have made every existing integration test that boots the
real FastAPI `lifespan` (via `app.router.lifespan_context`) require a real, reachable Redis —
none is available in this test environment (`pgserver` provides embedded Postgres; there is
no equivalent for Redis here). This was caught empirically: the first version of this change
did exactly that and every API test hung/failed at collection. The fix is the dependency
itself, not a workaround in each test.

**Offset pagination and a bare-array response, not `docs/api/API_DESIGN.md`'s documented
cursor+envelope design.** Every list endpoint shipped so far — `projects`, `plugin-
connections`, and now `agent-configs`/`.../runs`/`knowledge-items` — uses plain `limit`/
`offset` and returns a bare JSON array, matching `Repository.list_all`'s existing shape, not
the cursor-pagination/`{"data", "meta"}`-envelope design that document describes. Matching
the aspirational doc for only the two endpoints built in this task would have made the API
internally inconsistent (three plain-array endpoints and two enveloped ones) for no benefit —
adopting cursor pagination is a cross-cutting change worth doing once, consistently, across
every list endpoint, not piecemeal. `docs/api/API_DESIGN.md` now says this explicitly rather
than silently diverging from what it describes.

---

## 2. Architecture compliance summary

| Requirement | Compliance |
|---|---|
| Use the Reddit plugin exactly as implemented | **Yes.** Conversation Finder never imports `plugins.reddit` or references `"reddit"` as a string anywhere in `agents/conversation_finder/`. It calls `ctx.plugins.all_with_capability(Searchable)` and iterates whatever comes back. |
| Do not bypass the Plugin SDK | **Yes.** All plugin interaction goes through `PluginQuery`/`PluginResult`/`Searchable`/`PluginRegistry` — no direct HTTP calls, no reaching into a plugin's internals. |
| Do not add Reddit-specific logic to the platform | **Yes.** `ranking.py` reads only `title`/`body` (universal `PluginResult` fields); `platform` comes from `plugin.manifest.key`. Verified: a case-insensitive repo-wide search for `"reddit"` inside `agents/` and `backend/app/` turns up only doc-string prose — `agents/conversation_finder/config.py` and `README.md` explaining, by example, that subreddit-style config belongs on the plugin connection, not here (§1); `backend/app/core/plugin_catalog.py`'s pre-existing module docstring showing a generic entry-point example; and two other agents' still-unbuilt `README.md` specs (`content_agent`, `knowledge_base_agent`) mentioning Reddit as an example data source. No code anywhere branches on `plugin_key == "reddit"` or imports `plugins.reddit`. |
| Respect all existing ADRs | **Yes.** ADR 0006 (event-driven agent communication): Conversation Finder has zero reference to any other agent, only publishes `knowledge_item.created`. ADR 0007 (capability segmentation): uses `Searchable` only. ADR 0009 (plugin config schema): per-plugin search config stays on the plugin connection. ADR 0002 (Arq over Celery): reuses the existing agent-runs queue/worker, no new queue. |
| Preserve the event-driven architecture | **Yes.** `knowledge_items` row + `knowledge_item.created` event written in the same transaction via `ctx.events.publish(...)` (flush, not commit — the job owns the boundary), exactly as `docs/agents/AGENT_ARCHITECTURE.md` §Communication specifies. Only genuinely new rows publish; a refreshed re-discovery does not. |
| Preserve tenant isolation | **Yes.** Every write and read is scoped by `project_id` — `KnowledgeItemRepository`'s queries all filter on it, `knowledge_items`' `unique(project_id, url)` constraint is per-project, and every new API route depends on `require_project_access` (the single existing enforcement point), never an inline check. |
| Maintain strict typing, test coverage, and documentation standards | **Yes** — see §3. `mypy --strict` clean across every new/changed backend file and the entire `agents/conversation_finder/` package, including its own tests (a stricter bar than the Reddit plugin report's precedent, which left plugin test files out of the mypy pass — an intentional, low-risk improvement here, not a required one). `ruff check` clean. Documentation: this report, `agents/conversation_finder/README.md` (rewritten), `docs/knowledge-base/KNOWLEDGE_BASE.md` (Phase 2A note added), `docs/agents/AGENT_ARCHITECTURE.md` (roster updated), `docs/api/API_DESIGN.md` (pagination/envelope gap now stated explicitly), `ROADMAP.md` (step 5 marked half-done), `backend/README.md` (structure + "explicitly not present" list updated). |
| No AI reply generation / LLM integration / Content Agent / approval / publish / UI | **Yes, confirmed by absence.** `AgentContext.llm` stays `None` at every call site; no prompt, no LLM client, no `services/content_approval.py`, no publish trigger, no frontend code was touched. |

No frozen architectural decision, ADR, or locked decision
(`docs/architecture/LOCKED_DECISIONS.md`) was touched, reinterpreted, or worked around.

---

## 3. Test results

**54 new tests written for this work, all passing, zero regressions anywhere else:**

- `agents/conversation_finder/tests/` — **27 passed**:
  - `test_config.py` (7) — defaults, full-config acceptance, out-of-range rejection for
    every bounded field.
  - `test_ranking.py` (9) — no-terms/no-match zero score, title-beats-body weighting, full
    and partial coverage, case-insensitivity, dedup+sort of matched terms, a `None` title
    (the one field `PluginResult` actually allows to be absent) not raising, blank terms
    ignored.
  - `test_subscriptions.py` (2) — schedule-only means an empty tuple that matches nothing.
  - `test_agent.py` (9) — no-keywords-anywhere produces an error and does nothing;
    `icp_config` fallback; agent config takes priority over the fallback; results at/above
    `min_score_to_save` are saved and published, below are skipped; same-URL dedup within one
    run; a refreshed existing item does **not** re-publish an event; one plugin raising from
    `search()` doesn't fail the run (the healthy plugin's results still land); summary
    reports platforms searched and counts.
- `backend/tests/` new files — **27 passed**:
  - `test_agent_registry.py` (3) — loads the real installed agent, 404s on an unknown key,
    404s when a module has no `AGENT` singleton.
  - `test_knowledge_base_client.py` (4, integration) — creates a new row, refreshes an
    existing one by URL instead of duplicating, dedup is per-project (the same URL in two
    projects is two rows), `get_by_url` miss returns `None`.
  - `test_agent_config_service.py` (4, integration) — create + audit row, update-in-place on
    a second call, rejects config that fails the agent's own schema, rejects an unknown
    agent key.
  - `test_agent_runs_job.py` (4, integration) — full discovery-to-persistence run against the
    real `dummy` plugin (knowledge item + domain event both land, `source_agent_run_id` is
    stamped), no-op for a disabled config, no-op (not a crash) for a config deleted between
    enqueue and execution, a failing agent still records a `failed` run and re-raises for
    Arq's retry policy.
  - `test_agent_configs_api.py` (8, integration) — upsert succeeds/rejects invalid config/
    rejects unknown agent key, trigger enqueues a job and auto-provisions a default config,
    a second trigger reuses the existing config rather than creating another, trigger
    rejects an unknown agent key without enqueuing anything, run list starts empty,
    project-access is enforced.
  - `test_knowledge_items_api.py` (4, integration) — lists discovered items, filters by tag,
    empty for a new project, project-access enforced.

**Full suite totals:**
- `cd backend && pytest`: **203 passed** (176 before this task).
- `pytest agents plugins` (from repo root): **72 passed** (45 before this task — the Reddit
  plugin + dummy fixture + shared contract suites, unchanged).

**Lint/type-check:**
- `ruff check` — clean across every new/changed file (`backend/app/`, `agents/
  conversation_finder/`, including its tests). Two pre-existing `I001` (import-sort) findings
  remain in files this task didn't touch (`app/core/oauth/client.py`,
  `app/core/plugin_catalog.py`, `app/core/plugin_registry.py`, `app/core/subscriptions.py`,
  `app/services/oauth_connection.py`) — left alone as out of scope.
- `mypy --strict` — clean across all 73 files in `backend/app/` and all 10 source files in
  `agents/conversation_finder/` (including its own test suite). One invocation subtlety worth
  recording: checking `agents/conversation_finder` in isolation needs `MYPYPATH=backend` (not
  `PYTHONPATH`) alongside `--config-file backend/pyproject.toml` for its `TYPE_CHECKING`-only
  references into `app.*` to resolve — without it, mypy reports a spurious "missing library
  stubs" note that has nothing to do with this task's code (the same note would fire for
  `agents/_shared/base.py`'s pre-existing identical imports if checked the same way).

**End-to-end wiring, verified against the real mechanism, not asserted:**
```
$ discover_agent_subscriptions() → [('conversation_finder', ())]
$ load_agent('conversation_finder').key → 'conversation_finder'
```
`test_agent_runs_job.py` exercises the entire real chain — `agent_configs` row →
`PluginRegistry` (real `dummy` plugin, pip-installed editable) → `ConversationFinderAgent.run()`
→ `knowledge_items` + `domain_events` rows → `agent_runs` row — with no fakes standing in for
any platform component, only the external plugin surface (`dummy` returns a fixed
`PluginResult` instead of calling a real API, exactly like the Reddit plugin's own contract
tests do).

---

## 4. API documentation

All routes are project-scoped and depend on `require_project_access` (session-cookie auth,
org membership check) exactly like every existing route. Matches the resource paths
`docs/api/API_DESIGN.md` already specified for this area; see §1's scoping note for the two
respects (pagination, envelope) in which the *implementation* doesn't yet match that
document's aspirational shape.

| Method & path | Purpose |
|---|---|
| `GET /api/v1/projects/{project_id}/agent-configs` | List this project's agent configs. |
| `PUT /api/v1/projects/{project_id}/agent-configs/{agent_key}` | Create-or-update the config for `agent_key` — body `{config, schedule_cron?, enabled?}`. `config` is validated against that agent's own `config_schema` before writing (422 `validation_error` on failure); 404 if `agent_key` isn't installed. Writes an `audit_log` row (`agent_config.created`/`agent_config.updated`). |
| `POST /api/v1/projects/{project_id}/agent-configs/{agent_key}/runs/trigger` | On-demand run — enqueues the same `run_scheduled_agent` Arq job the cron scheduler uses. Auto-provisions a config (disabled schedule, empty config) if none exists yet. Returns `202 {agent_config_id, agent_key, status: "queued"}`. 404 for an unknown `agent_key`. Writes an `audit_log` row (`agent_config.run_triggered`). |
| `GET /api/v1/projects/{project_id}/agent-configs/{agent_key}/runs?limit=` | List this agent's `agent_runs` history for the project, newest first — the execution audit trail (`status`, `started_at`/`finished_at`, `summary`, `error`). |
| `GET /api/v1/projects/{project_id}/knowledge-items?tag=&limit=&offset=` | List discovered knowledge items, newest-discovered first. `tag` filters to items matching that exact tag. Read-only — nothing writes `knowledge_items` through the API. |

Example: configure and trigger a discovery run, then read what it found.

```bash
curl -X PUT http://localhost:8000/api/v1/projects/{project_id}/agent-configs/conversation_finder \
  --cookie "growthos_session=<cookie>" \
  -d '{"config": {"keywords": ["crawl budget", "canonical tags"], "min_score_to_save": 0.3}, "schedule_cron": "0 6 * * *"}'

curl -X POST http://localhost:8000/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs/trigger \
  --cookie "growthos_session=<cookie>"
# → 202 {"agent_config_id": "...", "agent_key": "conversation_finder", "status": "queued"}

curl http://localhost:8000/api/v1/projects/{project_id}/agent-configs/conversation_finder/runs \
  --cookie "growthos_session=<cookie>"

curl http://localhost:8000/api/v1/projects/{project_id}/knowledge-items \
  --cookie "growthos_session=<cookie>"
```

---

## 5. Remaining work before Phase 2B (Content Agent)

- **A real, connected Reddit account.** Nothing in this task or the prior one has connected
  an actual Reddit OAuth app — Conversation Finder has never made a real network call outside
  its own tests (against the real `dummy` fixture, and mocked/fake plugins). First real-world
  validation (does discovery actually surface relevant threads against production Reddit) is
  unstarted.
- **An LLM provider client.** Content Agent's entire purpose — reading a `knowledge_item` and
  drafting a reply/article — needs `AgentContext.llm` to be something real, per
  `docs/decisions/0004-llm-provider-abstraction.md`. Nothing built in Phase 1 or 2A provides
  this yet.
- **An LLM-based enrichment pass for `knowledge_items`.** Conversation Finder's rows are
  missing `problem`/`industry`/`product`/`pain_point`/real `buying_intent` — the fields
  Content Agent's subscription filter (`buying_intent in (medium, high)`, per
  `docs/agents/AGENT_ARCHITECTURE.md`) actually needs to be meaningful. Either Content Agent
  performs this extraction itself when it reacts to `knowledge_item.created`, or a separate
  enrichment step runs first — this task deliberately did not decide that, since deciding it
  requires designing Content Agent, out of scope here.
- **Content Agent itself** — `agents/content_agent/`, subscribing to `knowledge_item.created`
  (filtered by `buying_intent`), drafting a `content_items` row. Explicitly out of scope for
  this task.
- **`ContentApprovalService` and the publish worker** — still Phase 2B+ business logic, not
  built; `app/jobs/publish.py`'s body is still a placeholder.
- **The subscription-triggered job path (`run_agent_for_event` in `app/jobs/events.py`)** is
  still a placeholder — Conversation Finder is schedule-only, so nothing needed it yet.
  Content Agent (subscription-only, per the agent roster) is what will need it wired next,
  the same way this task wired `run_scheduled_agent`.
- **Observability** — `ARCHITECTURE.md` §10's planned OpenTelemetry spans on agent runs and
  plugin calls don't wrap this agent's work yet; not needed for it to function correctly, but
  relevant once real traffic flows through it.
- **Frontend** — no UI was built or touched, per this task's instructions; the API above is
  presently `curl`-only.

None of the above block Content Agent from being designed — they're the concrete list of what
it (and whatever enrichment step precedes it) would need to actually do, once building it is
back in scope.
