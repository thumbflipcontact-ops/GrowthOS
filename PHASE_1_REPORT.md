# Phase 1 Completion Report — Platform Foundation

**Date:** 2026-07-25
**Scope:** `ROADMAP.md` Phase 1, as re-scoped for this implementation pass — platform
foundation only (FastAPI app, configuration, logging, PostgreSQL, Alembic, repository layer,
dependency injection, authentication scaffold, Plugin SDK, plugin registry, event bus,
domain events, background workers, API skeleton, testing framework, local dev environment).
Explicitly **not** implemented: the Reddit plugin, any AI provider client, Conversation
Finder, Content Agent, CRM, Competitor Watch, or any other agent/plugin business logic.

**Constraint honored throughout:** no Docker was used for implementation or verification, per
explicit instruction. Everything below was built and tested against a real, locally-run
Postgres with zero containers — see §5. The existing Docker scaffolding was updated to match
the real code but deliberately left unbuilt; see §3 and §5.

---

## 1. Implementation summary

### Environment
- Python 3.12 (via `uv`, isolated — the host machine only has 3.13, and `pgserver`, the
  embedded-Postgres dependency this implementation relies on for Docker-free testing, has no
  Windows wheel for 3.13 yet). 3.12 also matches the version already pinned in
  `docker/Dockerfile.backend` from Phase 0, so this isn't a new commitment — the Docker image
  and local dev now agree.
- `backend/pyproject.toml`: a real, installable package (`growthos-backend`) with pinned
  dependencies — FastAPI, SQLAlchemy 2.0 (async), asyncpg, Alembic, Arq, structlog,
  argon2-cffi, itsdangerous, pgvector, croniter, plus dev extras (pytest, pgserver,
  fakeredis, ruff, mypy).

### Core (`backend/app/core/`)
`config.py` (typed `Settings`, fails fast on missing/invalid env), `logging.py` (structlog,
JSON in prod / console locally, secret redaction), `errors.py` (the full domain exception
hierarchy from `docs/errors/ERROR_HANDLING.md`, wired to FastAPI via one exception handler),
`security.py` (Argon2id password hashing, itsdangerous-signed session tokens, CSRF token
generation), `db.py` (async engine/session factory).

### Database (`backend/app/models/`, `backend/migrations/`)
All 17 tables from `database/schema.sql` as SQLAlchemy 2.0 models — organizations, users,
memberships, projects, plugin_catalog, plugin_connections, agent_configs, agent_runs,
domain_events, knowledge_items, content_items, audit_log, companies, contacts, competitors,
competitor_observations, daily_briefs. One Alembic migration applies the complete schema,
verified (not assumed) to match `schema.sql`: same table set, same 8 core-owned enums, `vector`
extension present, `content_items.type` confirmed `text` (not an enum) per ADR 0008.

### Repository layer & dependency injection (`backend/app/repositories/`, `backend/app/api/deps.py`)
A generic `Repository[Model]` base plus seven concrete repositories. `get_db` (request-scoped
session, commit-on-success), `get_current_user` (session-cookie resolution), and the
project/org authorization dependencies (`require_project_access`, `require_org_access`) — the
single enforcement point for tenant scoping, per `docs/auth/AUTHENTICATION.md`.

### Auth scaffold (`backend/app/services/auth_service.py`, `backend/app/api/v1/auth.py`)
`register` (the solo-operator bootstrap flow — org + owner user + membership in one
transaction, not a public signup flow), `authenticate`, and the HTTP endpoints
(`/auth/register`, `/auth/login`, `/auth/logout`, `/auth/me`). Every login attempt,
successful or not, writes an `audit_log` row, per `docs/security/SECURITY.md`.

### Plugin SDK (`plugins/_shared/`)
`manifest.py` (`PluginManifest`, `ContentTypeSpec`) and `base.py` (the four segmented
capability Protocols — `Searchable`, `Publishable`, `WebhookReceivable`, `MetricsQueryable`
— plus the shared dataclasses). Deliberately dependency-free of `backend/app`, matching the
documented design principle.

### Plugin catalog & registry (`backend/app/core/plugin_catalog.py`, `plugin_registry.py`)
Real `importlib.metadata` entry-point discovery (not a hand-maintained list), a `PluginCatalog`
with full-replace refresh semantics, DB sync (`plugin_catalog` table), and a `PluginRegistry`
enforcing the two independent capability gates (manifest declaration + project-level
enablement) documented in `docs/plugins/PLUGIN_ARCHITECTURE.md`, with a third structural
`isinstance` check as defense in depth. **Proven end-to-end**, not just unit-tested in
isolation: `plugins/dummy/` is a real, separately pip-installed package (its own
`pyproject.toml`, its own `growthos.plugins` entry point) that the test suite discovers via
the actual production discovery path — this is the "trivial hello world plugin" exit check
`docs/architecture/archive/MIGRATION_V1_TO_V2.md` specified.

### Event bus (`backend/app/core/events.py`, `subscriptions.py`, `dispatcher.py`)
`EventPublisher` (transactional outbox — writes in the caller's transaction, never commits
independently), `SubscriptionRegistry` (entry-point discovery mirroring the plugin catalog),
and `EventDispatcher` (core dispatch logic, decoupled from Arq via an injectable `enqueue`
callback so it's fully unit-testable). `agents/_shared/subscriptions.py` and `base.py`
(`EventSubscription`, `AgentSubscriptions`, `AgentContext`, `AgentResult`, the `Agent`
Protocol) — dependency-free of `backend/app` the same way the plugin SDK is.

### Background workers & scheduler (`backend/app/jobs/`, `backend/app/scheduler.py`)
Three Arq `WorkerSettings` (`agent_runs.py`, `events.py`, `publish.py`) matching the queue
separation documented in `docs/jobs/BACKGROUND_JOBS.md`, each with real startup/shutdown
lifecycle (DB engine) and — for `events.py` — the actual cron-scheduled dispatch job. Job
*bodies* are placeholders (`logger.info(...)`) since what they'd do is agent/publish business
logic, explicitly out of scope; the queue plumbing around them (retries, idempotency,
separate pools) is real. `app/core/scheduler.py` (`Scheduler.tick()`, `is_due()` cron
due-check) plus `app/scheduler.py` (the standalone process entrypoint).

### API skeleton (`backend/app/main.py`, `backend/app/api/v1/`)
FastAPI app factory with a real `lifespan` (creates the DB engine, discovers the plugin
catalog, syncs it to the database — this is the "plugin_catalog manifest scan at startup"
`docker-compose.yml`'s `backend` service was documented as hosting), a request-id middleware,
and routers: `health`, `auth`, `projects` (org-scoped list/create, project get — with real
authorization boundary tests), `plugins` (`GET /plugins/catalog`).

### Testing framework (`backend/tests/`)
`conftest.py` provisions a real, embedded Postgres via `pgserver` (session-scoped, torn down
completely at the end of the run) — no Docker, no system Postgres install — plus a
`fakeredis` fixture and a transactional `db_session` fixture (savepoint-based rollback, so
every test is isolated without truncating tables). 67 tests across `tests/unit/` and
`tests/integration/`.

### Local dev environment (`scripts/`, `backend/scripts/dev_postgres.py`)
Cross-platform Python scripts (not shell — one implementation works on Windows/macOS/Linux):
`setup.py`, `migrate.py`, `lint.py`, `seed.py`, plus `backend/scripts/dev_postgres.py` (runs
a real local Postgres with no Docker, no install). All five were actually run, not just
written — see §5.

### Docker scaffolding (`docker/`)
Updated to reference the real module paths (`app.jobs.agent_runs.WorkerSettings`, etc.) and
the real dependency-install mechanism (plain `pip install .` against `pyproject.toml` —
the original Phase 0 scaffolding assumed Poetry, which this implementation didn't use).
**Deliberately left unbuilt** — see §3.

---

## 2. Test results

```
ruff check .        →  All checks passed! (0 issues)
mypy app (strict)   →  Success: no issues found in 53 source files
pytest               →  67 passed, 0 failed
```

Coverage highlights (what's actually being verified, not just exercised):

- **Migration correctness**: the applied schema is diffed against the expected table set,
  the expected 8 core-owned enum types, confirms `content_items.type` is `text` (not an
  enum, per ADR 0008), and confirms the `vector` extension is installed.
- **Server-side defaults**: every `DEFAULT` clause `schema.sql` declares is verified via raw
  SQL inserts (not the ORM) — this is a regression test for a real bug found during this
  implementation, see §4.
- **The concurrency guard**: `content_items.version` compare-and-swap is tested directly,
  including the specific race the design review flagged — two concurrent "approve"-shaped
  updates reading the same version, exactly one succeeds, the other affects zero rows. This
  is the database-level primitive the (not-yet-built) `ContentApprovalService` will sit on,
  and it's the single most safety-critical invariant in the whole system per `ARCHITECTURE.md`
  §8 — tested now, before the service that depends on it exists.
- **Plugin discovery, end to end, for real**: `plugins/dummy/` is discovered via actual
  `importlib.metadata` entry points (not an injected list), the registry enforces both
  capability gates and rejects a plugin's own manifest lying about what it implements.
- **Event bus, end to end**: publish → filter-matched dispatch → mark-dispatched, including
  "an event with no subscribers is still marked dispatched" and "a rejected-by-filter event
  never enqueues."
- **Scheduler**: cron due-detection (including the deliberate "empty first tick" behavior),
  enabled/disabled/no-schedule agent_configs.
- **Full HTTP flows**: register → session cookie → `/me` → logout → login again; duplicate
  registration rejected; wrong password rejected; org-scoped project CRUD; a request for
  another org's projects correctly rejected; a missing project correctly 404s.

**One environment-specific note, not a code issue**: `pytest-cov` (and therefore `coverage`)
cannot be loaded on this machine — a Windows Application Control policy blocks the
`_sqlite3` DLL `coverage` depends on, even when coverage isn't invoked, because pytest
autoloads the plugin at startup. Worked around with `-p no:cov`; flagged here so it isn't
mistaken for something this codebase did wrong. A CI environment without that OS-level
restriction should have no trouble running coverage normally.

---

## 3. Remaining work

Everything below is explicitly out of Phase 1 scope, not a gap in what was attempted:

- **All agent/plugin business logic**: the Reddit plugin (ADR 0005), any AI provider client
  (Claude/OpenAI — config plumbing exists in `Settings`, no client code), Conversation
  Finder, Content Agent, Customer Finder, Competitor Watch, Outreach Assistant, Knowledge
  Base Agent.
- **`ContentApprovalService`**: the actual approve/reject service and API endpoints. The
  database-level mechanism it will use (the `version` CAS guard, the
  `review_fields_consistent` constraint) is built and tested — the service and endpoints
  that call it are not, since that's the state-machine *business logic* `ARCHITECTURE.md` §8
  describes, correctly out of this phase.
- **Envelope encryption implementation**: `plugin_connections.credentials_encrypted` and
  `credential_data_key_wrapped` columns exist; the actual encrypt/wrap/rotate code
  (`docs/decisions/0010`) is not written. No real credential has been stored, so nothing is
  currently at risk — but this must land before any real plugin OAuth token does.
- **Frontend**: zero code, as expected (Phase 2+).
- **Docker**: scaffolding is current but **unbuilt and unverified** — see §4.
- **Observability** (OpenTelemetry/Prometheus): not in the explicit Phase 1 deliverable list;
  the design review flagged it 🟠, meaning it shouldn't be deferred indefinitely once Phase 2
  starts producing real plugin traffic to observe.
- **`plugin_connections` write endpoints**: only `GET /plugins/catalog` exists. Creating a
  connection (validated against a plugin's `config_schema`) and the frontend's
  `DynamicConnectionForm` are Phase 2, tied to the first real plugin.
- **Login brute-force protection**: explicitly left flexible in
  `docs/architecture/LOCKED_DECISIONS.md` §2, not built — worth doing before this is ever
  exposed to the public internet with real user data behind it.

---

## 4. Architectural concerns discovered during implementation

Per your instruction, this section is a full accounting of everything implementation
surfaced that touches the frozen design — with my judgment on which needed to stop-and-ask
versus which were implementation bugs below the level of a locked decision. **Nothing below
required pausing implementation**; all four are reported here for visibility and so Phase 2
doesn't rediscover them.

1. **`database/schema.sql` required a pgcrypto extension it doesn't need.**
   `gen_random_uuid()` has been a core Postgres 13+ builtin since before this project's
   target version (PG16). The `create extension pgcrypto` line was already redundant, and it
   actively broke on `pgserver`'s minimal Postgres distribution, which doesn't bundle
   pgcrypto. **Fixed**: removed the line, added a comment explaining why. This is a DDL
   correctness fix — nothing in `ARCHITECTURE.md` or `LOCKED_DECISIONS.md` specifies
   pgcrypto as a decision, so this didn't rise to "architectural issue."

2. **Several SQLAlchemy models didn't faithfully mirror `schema.sql`'s column types.**
   `Mapped[str]` without an explicit type infers `VARCHAR`, not `text` as `schema.sql`
   specifies everywhere; several `Mapped[datetime]` columns were missing
   `DateTime(timezone=True)` and would have stored naive timestamps against a schema that
   specifies `timestamptz` throughout. Both were caught by tests written specifically to
   check the *database's* view of the schema (via `information_schema`), not just that the
   ORM round-trips correctly. **Fixed**: a `type_annotation_map = {str: Text}` on the shared
   `Base` class (so every model gets this right automatically, not column-by-column) and
   explicit `DateTime(timezone=True)` everywhere a timestamp is manually declared. This was
   an implementation bug in translating the frozen schema into SQLAlchemy, not a gap in the
   schema design itself — `schema.sql` was already correct.

3. **The plugin registry needed a convention for locating a plugin's *implementation*,
   which the frozen docs didn't fully specify.** `docs/plugins/PLUGIN_ARCHITECTURE.md`
   precisely specifies how a plugin's *manifest* is discovered (entry points →
   `PluginManifest`), but not how the registry finds the class/factory that actually
   implements the capability Protocols once it has the manifest. I established the
   convention `plugins.<plugin_key>.plugin` exposing a `create_plugin(connection) ->
   GrowthOSPlugin` factory function — documented in `plugin_registry.py`'s module docstring
   and proven by `plugins/dummy/plugin.py`. This is a genuine new convention, not something
   the frozen architecture already decided, so it's worth your explicit awareness even
   though I judged it low-stakes enough not to warrant pausing for approval (it's an
   additive implementation detail fully consistent with every locked decision, reversible
   without touching the schema or any ADR). **Recommend ratifying this as part of Phase 2's
   first real plugin, or amending it then if a better convention emerges** — it's cheap to
   change now, with zero real plugins depending on it yet.

4. **Real entry-point discovery means each plugin/agent needs its own installable
   package**, not just a subdirectory. For `importlib.metadata.entry_points()` to find a
   plugin's manifest, that plugin's entry-point metadata must be registered via an actual
   `pip install` (even `-e`) — which means `plugins/<name>/` needs its own minimal
   `pyproject.toml`, not just Python files. This is implied by ADR 0007's "entry points, not
   a hand-maintained list" but wasn't spelled out as a concrete packaging requirement in
   Phase 0 docs. `plugins/dummy/pyproject.toml` is the working reference. **Flagging this
   explicitly so Phase 2's Reddit plugin doesn't lose time rediscovering it.**

None of these four contradict a locked decision (`docs/architecture/LOCKED_DECISIONS.md`) or
an ADR. All are either DDL/ORM correctness fixes below the architecture's abstraction level,
or implementation conventions that fill in genuine gaps the frozen docs left open without
closing off any alternative.

---

## 5. What was actually verified (not just written)

Every claim in §1–2 was checked by running real commands against a real (non-mocked)
Postgres, not inferred from reading the code:

- `alembic upgrade head` applied cleanly from empty to the full 17-table schema, more than
  once, including after a full reset.
- Raw SQL inserts (bypassing the ORM entirely) confirmed every documented default and
  constraint.
- The full plugin discovery → registry → capability-check chain ran against a really
  pip-installed package, not a mock.
- The FastAPI app's actual `lifespan` ran (via `TestClient`/`AsyncClient` + explicit
  `lifespan_context`), including the real plugin catalog discovery-and-sync step.
- `scripts/setup.py`'s components, `migrate.py`, `lint.py`, and `seed.py` were each run for
  real against the same local Postgres, not just written and assumed correct.

---

## 6. Recommendation for Phase 2

In order:

1. **Build the Reddit plugin** (ADR 0005) using `plugins/dummy/` as the structural reference
   (manifest, `pyproject.toml`, entry point, capability Protocols) but with a real PRAW-backed
   client — this is the first real exercise of the plugin SDK end to end.
2. **Build `ContentApprovalService`** and the approve/reject API endpoints. The hard part (the
   concurrency-safe database primitive) is done and tested; this is now "write the service
   that uses it correctly," including the 100%-branch-coverage bar
   `docs/testing/TESTING.md` sets for exactly this component.
3. **Implement envelope encryption** (ADR 0010) before Reddit OAuth tokens are ever stored —
   sequence this before or alongside step 1, not after.
4. **Build Conversation Finder and Content Agent**, wired through the real event bus (a
   `knowledge_item.created` subscription is now something that can be tested against a real
   dispatcher, not just designed on paper).
5. **Do one real `docker compose up --build` pass** early in Phase 2, while the codebase is
   still small enough that a Docker-specific surprise is cheap to fix — don't let the
   unverified Docker path go stale for multiple phases.
6. **Add OpenTelemetry instrumentation** once the Reddit plugin gives you a real external
   call to actually trace — retrofitting observability onto zero real traffic doesn't teach
   you anything about whether the instrumentation is useful.

Architecture remains frozen. Nothing in this phase's implementation surfaced a reason to
reopen it — see §4 for the full, honest accounting of what came close.
