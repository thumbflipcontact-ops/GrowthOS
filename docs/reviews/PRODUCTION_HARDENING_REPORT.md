# Production Hardening Report (Phase 2D)

**Date:** 2026-07-26
**Scope:** every **High** (and Critical) severity issue from
`docs/reviews/PRODUCTION_READINESS_REVIEW.md`, in priority order, per this phase's explicit
instructions — no architecture changes, no ADRs touched, backward compatible, strict typing
maintained, a regression test for every bug fixed, documentation updated as each issue closed.
Medium/Low-severity findings were deliberately left open (see §4) — fixing them wasn't
required to safely resolve any High-severity issue, and the instructions were explicit not to
implement low-priority enhancements beyond that.

**No proposed fix required changing a frozen architectural decision.** Every fix below is a
targeted change to existing code (a wrong exception type, a missing check, an unwired
dependency) or new-but-additive code (a new module, a new optional setting) — consistent with
the review's own framing that none of this needed a redesign. Nothing here triggered the
"stop and ask" clause.

---

## 1. Issues found, how each was fixed, and tests added

### 1.1 Retry is silently non-functional across every background job (Critical, §3.1)

**Finding:** every job set `max_tries = 3`, but Arq only retries a job that raises its own
`arq.worker.Retry` — a plain exception (or a custom subclass like the old
`PublishAttemptFailed`) is treated as a permanent failure after exactly one attempt,
regardless of `max_tries`.

**Fix:** `backend/app/core/job_retry.py` (new) — `retry_backoff_seconds(job_try)`, exponential,
capped at 60s. `app/jobs/publish.py`, `app/jobs/agent_runs.py`, `app/jobs/events.py` now raise
`arq.worker.Retry(defer=retry_backoff_seconds(ctx.get("job_try", 1)))` at every point that used
to re-raise a plain exception or `PublishAttemptFailed` (which was removed — it never served
its purpose). `app/jobs/oauth_refresh.py` was checked and needed no change — it already
handles per-connection failures without ever raising to the job level.

**Tests:** `tests/unit/test_job_retry.py` (2, new — backoff formula). Three existing failure
tests were tightened from `pytest.raises(Exception)` / a since-removed custom exception to
`pytest.raises(Retry)` specifically — `test_publish_worker.py::
test_publish_failure_leaves_item_approved_with_error_and_raises_arq_retry`,
`test_run_agent_for_event_job.py::test_run_agent_for_event_records_a_failed_run_when_the_llm_call_fails`,
`test_agent_runs_job.py::test_run_scheduled_agent_records_a_failed_run_and_reraises_when_the_agent_errors`
— each now asserts the *type* Arq actually listens for, not just "raises something," which is
what would have caught this bug originally.

### 1.2 Event dispatch can double-deliver (High, R1)

**Finding:** `EventDispatcher.dispatch_pending` committed `dispatched_at` once for the whole
batch, and the `enqueue_job` call in `app/jobs/events.py` passed no `_job_id` — a crash
partway through a batch, or a dispatcher retry, could re-enqueue an already-processed
event/subscriber pair under a fresh job id, running it twice.

**Fix:** `app/core/dispatcher.py`'s `dispatch_pending` now commits per event, not once per
batch — narrowing a crash's blast radius to the one event mid-flight. `app/jobs/events.py`
gained `_event_job_id(event_id, agent_key)`, passed as `enqueue_job`'s `_job_id` — the same
pattern the publish job already used correctly, making a re-enqueue for the same
event/subscriber pair a no-op while the original is queued/running.

**Tests:** `test_event_bus.py::test_a_crash_partway_through_a_batch_only_loses_the_undispatched_tail`
(new) — an `enqueue` callback that raises on the second of two events; asserts the first
event's `dispatched_at` survives the crash. `test_run_agent_for_event_job.py::
test_dispatch_domain_events_enqueues_with_a_deterministic_job_id` (new) — asserts the actual
`_job_id` kwarg passed to a fake Redis client.

### 1.3 Connection-pool budget is unmanaged (High, SC2)

**Finding:** every process created its own SQLAlchemy engine at default pooling
(5 + 10 = 15 connections), with six processes already summing to ~90 against Postgres's
default `max_connections=100` — one more worker replica away from exhaustion, with no way to
tune it short of a code change.

**Fix:** `Settings.db_pool_size`/`db_max_overflow` (new, defaulting to SQLAlchemy's own prior
implicit values — zero behavior change unless tuned). `app/core/db.py`'s `create_engine` now
accepts `pool_size`/`max_overflow` params; all six engine-creation sites (`main.py`,
`scheduler.py`, and the four job files' `startup()`) pass them from `Settings`.
`docs/scalability/SCALABILITY.md` gained a "Database connection budget" section with the
actual formula and concrete next steps (lower the pool per-process, raise Postgres's own
limit, or introduce PgBouncer) before adding more replicas.

**Tests:** `tests/unit/test_db_engine_config.py` (2, new — custom values applied; defaults
match prior behavior). `test_config.py` gained 2 tests for the new settings fields.

### 1.4 `GET /health` always says "ok" (High, O1)

**Finding:** unconditional `{"status": "ok"}`, no DB or Redis check — any orchestrator or
uptime monitor wired to it would report healthy through a real outage.

**Fix:** `app/api/v1/health.py` rewritten — checks `SELECT 1` against the real engine and
`PING`s the Arq Redis pool, returns 503 with a per-check error string if either fails.

**Tests:** `test_api.py::test_health` updated for the new response shape (happy path — real
pgserver-backed DB, a fake Redis with a working `.ping()`). `tests/integration/test_health.py`
(new) — the actual regression test, an unreachable-Redis fake proving 503 + per-check detail,
not just "still returns 200."

### 1.5 No automated migration step, and nothing catches a forgotten one (High, O7)

**Finding:** migrations only ever run manually (`scripts/migrate.py`); nothing checks whether
a running process's connected database is actually at the revision the code expects, so a
forgotten migration fails confusingly at the first query touching new schema, not loudly at
startup.

**Fix:** `app/core/migration_check.py` (new) — `verify_database_is_migrated(engine)` compares
the database's `alembic_version` row against the code's own Alembic head
(`ScriptDirectory.get_current_head()`) and raises `DatabaseNotMigrated` if they differ. Wired
into every process's startup (`main.py`'s lifespan, `scheduler.py`'s `main()`, and all four
jobs' `startup()`) — a process now refuses to start at all against a stale schema, rather than
degrading into confusing errors later. `docs/deployment/DEPLOYMENT.md`'s "Migrations" section
updated to describe both halves (the manual step, and this automatic safety net).

**Tests:** `tests/integration/test_migration_check.py` (3, new) — passes silently against the
real migrated test database; raises when the expected revision is patched to something that
doesn't match (without mutating the shared test database's actual state); no-ops when there
are no migrations to compare against.

### 1.6 Zero error-tracking/observability tooling (High, O8/O9)

**Finding:** no OpenTelemetry, no Prometheus, no error-tracking SDK anywhere — a background
worker failing silently is the single worst failure mode for a system whose value proposition
is "runs unattended," and today the only record is a local stdout log line.

**Fix:** `app/core/observability.py` (new) — `init_error_tracking(settings, process_name)` and
`capture_exception(exc)`, both fully optional and no-op unless `SENTRY_DSN` is set (new,
optional `Settings` field). Wired into every process's startup and into the two places an
unexpected error is actually logged: `app/core/errors.py`'s `>=500`/catch-all exception
handlers, and each job's failure path (`agent_runs.py`, `events.py`, `publish.py`). This is
deliberately **not** the full `docs/observability/OBSERVABILITY.md` stack (OTel spans,
Prometheus metrics, dispatch-lag alerting) — that remains future work; this closes the
narrower, more urgent "don't fail silently" gap the review flagged as the highest-severity
observability finding.

**Tests:** `tests/unit/test_observability.py` (4, new) — no-op without a DSN; initializes and
forwards to a mocked `sentry_sdk` when one is configured; `capture_exception` is a no-op
before init.

### 1.7 No rate limiting on login (High, S1)

**Finding:** `docs/security/SECURITY.md` explicitly claimed login was rate-limited per
account and per source IP; nothing enforced it anywhere.

**Fix:** `app/core/rate_limit.py` (new) — a generic, in-process token-bucket limiter (same
algorithm as the pre-existing `plugins/_shared/rate_limit.py`, deliberately not reused
directly since that module is keyed specifically for plugin-author use, not backend routes).
`app/api/deps.py` exposes two overridable dependencies,
`get_login_ip_limiter`/`get_login_account_limiter` (10/5min per IP, 5/15min per account),
checked in `POST /auth/login` before the Argon2id password verify runs at all. A new
`TooManyRequests` (429) domain error (`app/core/errors.py`) is raised on exhaustion.
**Known limitation, documented, not fixed this phase**: process-local only, same as the
plugin rate limiter's own documented limitation — a future multi-replica backend would need a
shared (Redis) backend behind the same interface.

**Tests:** `tests/unit/test_rate_limit.py` (4, new — capacity/exhaustion, per-key isolation,
refill, invalid construction). `tests/integration/test_auth_rate_limiting.py` (3, new) — 429
after the per-IP limit is exhausted, 429 after the per-account limit is exhausted, and a
rate-limited account doesn't affect a different one — each using dependency-overridden,
test-scoped tiny-capacity limiter instances so the production-sized defaults are never
touched by, or leaked between, tests.

### 1.8 A crash at exactly the wrong moment could duplicate a real Reddit post (Medium-High, R2)

Not a strict "High," but included: a narrow-window, high-impact correctness gap directly
adjacent to the retry fix (§1.1) and flagged prominently in the readiness review's top-10
punch list.

**Finding:** in `publish_content_item`, the plugin's `publish()` call (a real, irreversible
external side effect) happens before the transaction recording success is committed. A crash
in that window, followed by a re-run (a manual retry, or any future automatic redelivery),
would call the plugin a second time — a duplicate live Reddit comment.

**Fix:** before calling a plugin, the job now checks `content_publish_attempts` for a prior
row with `success=True` for the same item. Finding one means "this already posted, the crash
happened before that success was ever recorded against the item" — the job reconciles the
item to `published` using that attempt's own recorded URL instead of posting again.

**Tests:**
`test_publish_worker.py::test_publish_recovers_from_a_prior_successful_attempt_without_posting_again`
(new) — pre-inserts a successful attempt row for an item still `approved` (exactly the state
a crash in that window leaves behind), asserts the fake plugin's `publish()` is never called
again, the item still ends up `published`, and the audit/event trail reflects the recovery.

### 1.9 The OAuth token-refresh worker was never actually deployed (High, O12)

**Finding:** `app/jobs/oauth_refresh.py` is a real, tested, fully-implemented periodic sweep
— but no service definition anywhere ever ran it. Every connected OAuth plugin would
eventually degrade to `expired` purely because nothing invoked the refresh built to prevent
that.

**Fix:** `docker/docker-compose.yml` gained a `worker-oauth-refresh` service (matching the
other three worker types' shape exactly). `docs/deployment/DEPLOYMENT.md`'s "Services" list
and new "Non-Docker deployment" section both now name it explicitly, with the actual
`arq app.jobs.oauth_refresh.WorkerSettings` command required to run it without Docker (the
project's actual current mode of operation — see §2).

**Tests:** none needed — this was a deployment-configuration gap, not a code defect; the job
itself already had its own test coverage from when it was built.

### 1.10 Documentation/reality mismatches corrected alongside the fixes above

Several docs made claims that were false before this phase and are now either true (fixed) or
honestly corrected to describe the actual gap:

- `docs/jobs/BACKGROUND_JOBS.md`'s retry/idempotency claims — were false, now true (§1.1,
  §1.2), with the one remaining gap (the on-demand agent-trigger endpoint and the scheduler's
  own enqueue still lack a job id — R3, medium, not fixed this phase) called out explicitly
  rather than left implied-fixed.
- `docs/errors/ERROR_HANDLING.md`'s "retried with exponential backoff" claim — was false, now
  true.
- `docs/security/SECURITY.md`'s brute-force-protection claim — was false, now true (§1.7); its
  webhook-ingress claim — was false (no such endpoint exists), corrected to describe it as
  planned, not implemented.
- `backend/app/core/security.py`'s own docstring claimed the CSRF double-submit cookie was
  "checked on state-changing requests" — it never was. Corrected to describe reality (cookie
  set, never verified) and note this as a tracked, not-yet-fixed gap (S2, medium severity).
- `docs/observability/OBSERVABILITY.md` — added an explicit note that the full OTel/Prometheus
  design remains 0% built, distinguishing it clearly from the new baseline error tracking.

---

## 2. Architecture compliance summary

| Requirement | Compliance |
|---|---|
| Do not redesign the architecture | **Yes.** No component was replaced or restructured; every fix is a targeted change to existing logic or a small additive module (`job_retry.py`, `migration_check.py`, `observability.py`, `rate_limit.py`) following existing patterns in the codebase (e.g. `rate_limit.py` deliberately mirrors `plugins/_shared/rate_limit.py`'s already-reviewed design). |
| Preserve all ADRs | **Yes.** No ADR was touched, reinterpreted, or worked around. |
| Preserve backward compatibility | **Yes.** Every new `Settings` field has a default matching prior implicit behavior (`db_pool_size=5`, `db_max_overflow=10`, `sentry_dsn=None`); `create_engine`'s new params are keyword-only with matching defaults; nothing existing changes behavior unless newly-added config is explicitly set. |
| Maintain strict typing | **Yes** — `mypy` (project config, `strict = true`) clean across all 88 files in `backend/app/`, see §3. |
| Maintain comprehensive tests | **Yes** — 25 new tests (294 backend + 106 agents/plugins = 400 total, all passing), see §3. |
| Update documentation as each issue is resolved | **Yes** — each fix in §1 names the doc(s) updated alongside it; no fix was left undocumented. |
| Add regression tests for every production bug that is fixed | **Yes** — every bug fix in §1.1–1.2, 1.4–1.5, 1.8 has a test that would have failed against the old, buggy code and passes against the fix; §1.3, 1.6, 1.7 (new capability, not a bug fix per se) have direct unit/integration coverage of the new behavior. |
| Do NOT implement low-priority enhancements unless required to safely resolve a high-priority issue | **Yes, confirmed by scope.** Medium/Low findings (S2 CSRF verification, S3 KDF, S4 session revocation, S6 timing, S7 role enforcement, S8 dependency lockfile, SC1/SC3/SC4/SC5 various, O2/O3/O4/O6/O9/O10/O11 partially) were left open — see §4 — except where documentation itself was actively misleading (§1.10), which is a correctness fix to what's already there, not a new feature. |
| Stop and ask before any fix requiring a frozen architectural decision to change | **N/A — never triggered.** No proposed fix required one. |

---

## 3. Test results

**400 total tests, all passing** (294 backend + 106 agents/plugins — up from 375 at the end of
Phase 2C): 25 new tests across `test_job_retry.py` (2), `test_rate_limit.py` (4),
`test_observability.py` (4), `test_migration_check.py` (3), `test_health.py` (1),
`test_auth_rate_limiting.py` (3), `test_db_engine_config.py` (2), `test_config.py` (+3),
`test_publish_worker.py` (+1), `test_event_bus.py` (+1), `test_run_agent_for_event_job.py`
(+1); three existing tests tightened to assert `arq.worker.Retry` specifically instead of a
generic exception (§1.1); two existing tests updated for the new `/health` response shape and
the new login-rate-limiting-aware `api_client` fixture.

**Lint/type-check:** `ruff check` clean; `mypy` (project's own `strict = true` config, via
`python scripts/lint.py` — not a bare `mypy --strict` invocation, which would incorrectly
override the config's deliberate `disallow_any_generics = false` relaxation and produce dozens
of false positives across pre-existing files) clean across all 88 files in `backend/app/`.

**One pre-existing, unrelated flaky test noted, not fixed**:
`test_oauth_api.py::test_callback_rejects_tampered_state` intermittently fails when run as
part of the full suite (passes reliably in isolation across repeated runs). Confirmed to
reproduce identically *before* any Phase 2D code was written, and no file this phase touched
is anywhere near OAuth state signing/verification — out of scope for this phase's mandate
(not one of the readiness review's findings), noted here rather than silently ignored.

---

## 4. Remaining known production risks

Everything below was identified in `docs/reviews/PRODUCTION_READINESS_REVIEW.md`, deliberately
left open this phase (Medium/Low severity, or explicitly scoped out per this phase's "no
low-priority enhancements" instruction):

- **CSRF double-submit check is still unimplemented** (S2) — the cookie is set, nothing
  verifies it against a request header. `SameSite=Lax` mitigates the classic cross-site-POST
  case in the meantime.
- **Master-key derivation uses a single SHA-256 pass, not a real KDF** (S3).
- **No server-side session revocation** — a compromised session can only be invalidated by
  rotating the global `secret_key`, which invalidates every session at once (S4).
- **Account-enumeration timing gap** in `authenticate()` (S6).
- **`MembershipRole` is defined but never enforced** — every org member is effectively an
  owner; fine for today's single-owner-per-org reality, a real gap the moment an invite
  feature ships (S7).
- **No dependency lockfile** — version ranges, not pins (S8).
- **R3**: the on-demand agent-trigger endpoint and the scheduler's own periodic enqueue still
  lack a deterministic job id — a network retry/double-click there can enqueue two independent
  agent runs (medium severity, unlike R1/R2 which were fixed).
- **Missing composite indexes** on `content_items`/`knowledge_items` for their actual
  `ORDER BY` pattern (SC1).
- **Reddit plugin's rate limiter remains process-local**, not shared across replicas (SC3) —
  same accepted limitation as the new login rate limiter (§1.7).
- **No LLM call concurrency throttle** beyond Arq's incidental per-process job concurrency
  default (SC4).
- **No retention/archival story** for append-only tables, correctly deferred until real volume
  makes it matter (SC5).
- **Backups remain a documented manual procedure, not automation** — per explicit decision
  this phase (the real hosting target isn't chosen yet, so scripting it now risks scripting
  the wrong thing); see `docs/deployment/DEPLOYMENT.md`'s "Backups" section for the concrete
  `pg_dump`/`pg_restore` commands to run manually until it is automated.
- **Process supervision (auto-restart on crash) remains a documented requirement, not a
  shipped configuration** — per explicit decision this phase, for the same reason (host/
  supervisor choice not yet made); `docs/deployment/DEPLOYMENT.md`'s "Process supervision"
  section names the requirement and the generic options (systemd, Docker's `restart:`, a
  process manager) without committing to one.
- **`docker/docker-compose.yml` remains unbuilt/unverified** — the `worker-oauth-refresh`
  addition (§1.9) is structurally consistent with the rest of the file but, like every other
  service in it, has never been run against a real `docker compose build && up`.
- **Full OpenTelemetry/Prometheus observability stack remains 0% built** — only the narrower
  baseline error-tracking piece (§1.6) shipped this phase.
- **No CI pipeline exists** (`.github/` or equivalent) — every "PR opened → lint + tests" step
  described in `docs/deployment/DEPLOYMENT.md`'s CI/CD section is intent, not a running system.
- **A real, connected Reddit account and a real Anthropic API key have still never been used**
  — nothing in this phase or any prior one has exercised the full discover → draft → approve →
  publish chain against real external services.

None of the above block a careful solo operator from launching — the items §6 of the
readiness review called genuine launch blockers (the retry bug, no backups, the fake health
check, no restart policy, connection-pool math, event-dispatch duplication, no login rate
limiting, the unverified deployment path) are now either fixed (retry, health check,
connection pool, event dedup, rate limiting) or have a concrete, actionable manual procedure
where automation was deliberately deferred (backups, process supervision, the Docker
verification pass). What remains above is worth tracking and closing incrementally, not a
reason to delay further.
