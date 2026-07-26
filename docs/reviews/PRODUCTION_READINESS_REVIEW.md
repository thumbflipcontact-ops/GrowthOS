# Production Readiness Review

**Date:** 2026-07-26
**Scope:** the entire GrowthOS platform as of `v0.6.0-approval-publishing` (Phase 0 through
Phase 2C) — platform foundation, OAuth2 framework, Plugin SDK, Reddit plugin, Conversation
Finder, Knowledge Base, Content Agent, self-check, approval workflow, publish worker,
background jobs, APIs, security, multi-tenancy, configuration, logging, error handling, retry
behavior, observability, performance, scalability, deployment, operational readiness,
documentation, and testing.

**Reviewer stance:** assume this is about to be handed real users' real Reddit OAuth
credentials and will actually post to Reddit on their behalf, unattended, every day. This is
not a code-quality review and it does not revisit `ARCHITECTURE.md`'s frozen design decisions
— it asks one question about the *implementation* of that design: **if this shipped to a real
customer today, what would actually break, leak, or silently lose data, and how bad would it
be?**

**Method:** every finding below was verified against the real repository state — file read,
line cited, and (for the highest-severity claims) independently re-verified a second time
directly against source, not just trusted from a single pass. Nothing here is inferred from
what a doc *says* should be true. Several findings are exactly that gap: a doc, a docstring, or
a prior implementation report (including this project's own Phase 2C reports) asserting
something works that a direct read of the code shows does not.

**Headline verdict: not production-ready.** The domain modeling, tenant isolation, and the
approval state machine are genuinely solid — a real engineering achievement for four phases of
work. But the review surfaced one platform-wide correctness bug that quietly defeats retry
behavior everywhere it's claimed to exist, and a cluster of operational gaps (no backups, no
restart policy, a health check that always says "ok") that would turn any transient failure
into either silent data loss or a permanent, invisible outage. None of this requires a
redesign. All of it is fixable in days, not weeks — see §6.

---

## 1. Production Readiness Report

### What's genuinely ready

- **The core domain model and state machine.** `content_items`' five-state lifecycle
  (`draft → pending_review → approved → published`, plus `rejected`/`archived`), enforced
  exclusively by `ContentApprovalService`'s atomic, version-guarded `UPDATE`, is correct and
  well-tested (375 tests, `mypy --strict` clean). Concurrent double-approve/reject genuinely
  cannot both succeed — verified in this project's own Phase 2C test suite and independently
  re-confirmed by this review's tenant-isolation audit (§2).
- **Tenant isolation at the application layer.** Every project-scoped route depends on
  `require_project_access`, which genuinely checks org membership (not just project
  existence — `backend/app/api/deps.py:91-116`), and every repository method that fetches by
  id re-scopes to `project_id` in the same query. This review found **zero IDOR
  vulnerabilities** across a full audit of every route in `backend/app/api/v1/`. This is the
  single most safety-critical property of a multi-tenant system, and it holds.
- **Envelope encryption and the OAuth2 flow.** AES-256-GCM with a fresh random data key per
  row, genuine PKCE (S256), a signed and expiring CSRF-bound state token, and a fixed
  (never request-derived) redirect URI — all independently verified correct. This is
  production-grade OAuth2 implementation, not a toy.
- **No SQL injection, no unsafe deserialization, no shell/subprocess exposure** anywhere in
  the backend — confirmed by direct grep and spot-read, not assumed.

### What's not ready

Three categories of problem, in descending order of how surprising and dangerous they are:

1. **A platform-wide bug silently defeats retry behavior everywhere it's documented to
   exist** — every background job (`agent_runs`, `events`, `publish`, and by implication
   `oauth_refresh`) is configured with `WorkerSettings.max_tries = 3`, but Arq (the job queue
   library) only retries a job that raises its own `arq.worker.Retry` exception; every job in
   this codebase raises a plain exception instead, which Arq treats as a **permanent** failure
   after exactly one attempt. See §3.1 — this is the single most important finding in this
   review, because it means "retried up to 3 times with exponential backoff," a claim repeated
   across `docs/jobs/BACKGROUND_JOBS.md`, `docs/errors/ERROR_HANDLING.md`, this project's own
   `app/jobs/publish.py` docstring, and the Phase 2C implementation reports this review's
   author wrote two turns ago, has never once been true.
2. **Operational scaffolding a system meant to "run unattended every morning" cannot actually
   run unattended without.** `GET /health` returns `{"status": "ok"}` unconditionally with no
   DB/Redis check (`backend/app/api/v1/health.py:10-12`); no service in `docker-compose.yml`
   has a `restart:` policy, so a crashed worker just stays dead; and there is no backup
   automation, WAL archiving, or disaster-recovery procedure anywhere in the repository for a
   Postgres instance that is the sole copy of the "institutional memory" knowledge base. See
   §5.
3. **A handful of narrower but real correctness/security gaps** — event dispatch can
   double-deliver (no idempotency key), a crash inside the publish worker at exactly the wrong
   moment could theoretically cause a duplicate Reddit post, there's no rate limiting on login,
   and a CSRF cookie is generated and documented as checked but is never actually verified
   anywhere. See §2 and §3.

None of this contradicts the Phase 2C implementation reports' own architecture-compliance
claims — those were scoped to "does this match `ARCHITECTURE.md` §8's state machine," which it
does. This review asks a different, broader question and found a different, broader set of
gaps. The state machine is correct; the infrastructure underneath it running unattended in
production is not yet trustworthy.

### API design consistency (cross-cutting, referenced by later sections)

- `docs/api/API_DESIGN.md` documents cursor pagination, a `{data, meta}` response envelope,
  and an `Idempotency-Key` header on side-effectful POSTs. **None of the three is implemented**
  — confirmed current, the doc's own "not yet true of any shipped endpoint" caveats are
  accurate and up to date for the first two. The third (`Idempotency-Key`) is documented as
  implemented on `.../approve` and `.../runs/trigger`; it exists on neither
  (`backend/app/api/v1/content_items.py`, `backend/app/api/v1/agent_configs.py:60-87`).
  `approve`'s double-submit case is adequately covered by the version guard plus the publish
  job's deterministic Arq job id, so this is low-risk there — but `trigger_agent_run`
  (`agent_configs.py:60-87`) enqueues with no job id at all, so a retried/double-clicked
  request genuinely queues two independent agent runs. Medium severity, see §6.
- Error responses are only uniform for domain-raised errors. Anything FastAPI's own validation
  catches before a handler runs (a malformed UUID in a path, an out-of-range query param) falls
  through to FastAPI's default `{"detail": [...]}` shape instead of the documented
  `{"error": {...}}` envelope (`backend/app/core/errors.py:89-126` never registers a
  `RequestValidationError` handler). A client written strictly against the documented envelope
  will fail to parse these responses. Medium severity.
- Two list endpoints (`agent-configs`, `plugin-connections`) have no `limit`/`offset` params at
  all, unlike every other list endpoint, and return every row unbounded. Low risk today (bounded
  by catalog/config cardinality, not attacker-controlled), but inconsistent and will not stay
  low-risk once the plugin/agent catalog grows.
- No CORS configuration exists anywhere. Safe by omission today (no cross-origin frontend
  exists yet); flagged here only because Phase 2 (per `ROADMAP.md`) adds a frontend, and the
  wrong fix (`allow_origins=["*"]` combined with the cookie-based, credentialed session auth
  this app already uses) would be a critical misconfiguration to avoid making at that time.

---

## 2. Security Review

### 2.1 Findings

| # | Finding | File(s) | Severity |
|---|---|---|---|
| S1 | No rate limiting or lockout on `POST /auth/login` anywhere in the codebase (no middleware, no per-route throttle). Argon2id slows a single guess but nothing stops distributed/automated credential stuffing. **Directly contradicts `docs/security/SECURITY.md`'s explicit claim** that login is "rate-limited per account and per source IP." | `backend/app/api/v1/auth.py`; grep-confirmed absent repo-wide | **High** |
| S2 | A CSRF cookie is generated on login and deleted on logout (`auth.py:41-46,89`), and both `core/security.py`'s own docstring and `docs/security/SECURITY.md` describe it as "checked on state-changing requests" — but it is **never actually verified anywhere**. No dependency, middleware, or route compares the cookie to a header. Verified by grepping every reference to the CSRF cookie constant across the backend. Partially mitigated in practice by `SameSite=Lax` on the session cookie (blocks the classic cross-site form-POST case), but the stated double-submit defense doesn't functionally exist. | `backend/app/core/security.py`, `backend/app/api/v1/auth.py`, `backend/app/api/deps.py` (no check present) | **Medium** |
| S3 | `derive_master_key()` reduces the operator-supplied `CREDENTIAL_MASTER_KEY` to 32 bytes via a single unsalted SHA-256 pass, not a real key-derivation function (PBKDF2/scrypt/HKDF with a work factor). A low-entropy operator secret is bruteforceable offline with no cost multiplier if a wrapped data key is ever exposed. The AES-256-GCM envelope scheme itself (fresh random data key per row, correct nonce handling) is sound and independently verified correct. | `backend/app/core/crypto.py:26-32` | **Medium** |
| S4 | Session tokens are stateless itsdangerous signatures with no server-side session store — there is no way to revoke one specific compromised session short of rotating the global `secret_key`, which invalidates every session and every in-flight OAuth state simultaneously. `docs/security/SECURITY.md`'s incident-response runbook ("invalidate all sessions") has no narrower mechanism to invoke. | `backend/app/core/security.py` | **Medium** |
| S5 | Secret redaction in structured logging is a top-level-key-name allowlist (`_REDACTED_KEYS`) — it does not recurse into nested objects, and does not scrub secret material embedded in free-text exception messages. `oauth/client.py` builds exception messages containing up to 500 raw characters of a token endpoint's error response body; if a provider's error response ever echoes token material, it reaches the logs unredacted via `exc_info=True` logging in the error handler. No confirmed active leak found (Reddit's error bodies are unlikely to contain the bearer token itself), but the redaction mechanism has this structural gap. | `backend/app/core/logging.py:49-65`, `backend/app/core/oauth/client.py:142,148`, `backend/app/core/errors.py:96-99` | **Medium** |
| S6 | `authenticate()` short-circuits with an early return when no account exists, before ever calling the (deliberately slow) Argon2id verify — an attacker can distinguish "no such account" from "wrong password" via response timing, enabling account enumeration despite an identical error message. | `backend/app/services/auth_service.py:60-68` | **Low/Medium** |
| S7 | `MembershipRole` (owner/member) is defined and set at registration, but **is never read anywhere** in authorization logic — every dependency checks membership *existence* only, never role. There is also no invite/add-member endpoint at all; the only way a membership is created is `/auth/register`, which always assigns `OWNER`. Fully decorative today (acceptable for a genuinely single-owner-per-org v1), but the moment an invite/multi-user feature ships without adding role checks first, every invited "member" gets full owner-equivalent access — including approving/publishing content and reconfiguring plugin credentials. | `backend/app/models/identity.py:42-45`, `backend/app/api/deps.py` | **Medium, contingent on a future feature** |
| S8 | Dependencies are pinned to minor-version ranges (`>=x,<y`), not exact versions, with no lockfile — builds aren't fully reproducible and a compromised patch release within an allowed range could be pulled silently on a fresh install. | `backend/pyproject.toml` | **Low/Medium** |
| S9 | No minimum-length/entropy validation on `secret_key`/`credential_master_key` in `Settings` — a weak short string is silently accepted rather than rejected at startup. | `backend/app/core/config.py` | **Low** |
| S10 | `docs/security/SECURITY.md`'s webhook-ingress section describes a live, HMAC-verified, rate-limited `/webhooks/{plugin_key}` endpoint in the present tense. **No webhook route exists anywhere in the codebase.** Not itself exploitable (nothing to attack), but the doc reads as an implementation claim rather than a plan, and a reader (including future contributors) could reasonably believe webhook ingress is already secured. | grep-confirmed absent repo-wide | **Informational** (doc/reality mismatch) |

### 2.2 Confirmed clean (verified, not assumed)

- **No IDOR anywhere.** Full route-by-route audit of `backend/app/api/v1/`; every resource id
  is re-scoped to the resolved, membership-checked project before use.
- **No SQL injection, unsafe deserialization, or shell/subprocess exposure** anywhere in
  `backend/app`.
- **PKCE, OAuth state signing/expiry, and fixed redirect_uri** are all correctly implemented —
  a genuinely solid OAuth2 flow.
- **No CORS misconfiguration** — none exists yet, which is safe by omission (see §1).
- **`.env` is gitignored; `.env.example` ships no real secret values.**
- **Envelope encryption's core cryptography (AES-256-GCM, per-row data keys, nonce handling)**
  is sound — S3 above is about the *master key's* derivation, not the envelope scheme itself.

---

## 3. Reliability Review

### 3.1 The retry bug (top finding of this entire review)

Every `WorkerSettings` class in this codebase sets `max_tries = 3` (or Arq's default of 5):
`backend/app/jobs/publish.py:208`, `agent_runs.py`, `events.py`, `oauth_refresh.py`. This
setting is meaningless as written. Arq's worker loop (verified directly against
`arq/worker.py:604-625` in this project's own installed dependency) only re-queues a job when
the job function raises `arq.worker.Retry` — every other exception, including a plain `raise`
or a custom exception class like this codebase's own `PublishAttemptFailed(Exception)`
(`publish.py:46`), is caught by the `else` branch, logged, and the job is marked **permanently
failed after exactly one attempt**. `max_tries` is never even consulted in that path.

Concretely: Reddit returns a transient 503 during a publish attempt. `publish_content_item`
records the failed attempt, commits, and raises `PublishAttemptFailed` — intending to trigger a
retry. Arq sees a plain exception and finishes the job for good, on try 1 of the supposed 3.
The item is left `approved` with `publish_error` set, indistinguishable from a real
exhausted-all-retries case, but only one attempt ever happened. The identical bug applies to
`run_scheduled_agent` and `run_agent_for_event` — a single transient LLM or network blip
permanently fails an agent run with zero automatic recovery.

This is not silent data loss (every job type has a durable failure record — `publish_error`,
an `agent_runs` row with `status=failed` — so nothing vanishes without a trace), but it means
**the "error handling and retry support" requirement this project's own Phase 2C instructions
explicitly asked for, and which this review's author's own prior implementation reports
described as delivered, has never functioned.** `docs/jobs/BACKGROUND_JOBS.md`'s "retried up to
3 times with exponential backoff" and `docs/errors/ERROR_HANDLING.md`'s equivalent claim are
both false as written. **Severity: Critical.** The fix is small and contained (raise
`arq.worker.Retry(defer=...)` instead of a plain exception at each of the four re-raise sites)
but does not qualify as "extend the existing architecture" — the *intent* (retry with backoff)
was correct throughout; only the mechanism used to invoke it was wrong everywhere it appears.

### 3.2 Idempotency and duplicate-delivery risk

| # | Finding | File(s) | Severity |
|---|---|---|---|
| R1 | `dispatch_pending` enqueues one Arq job per subscriber for every undispatched event, then sets `dispatched_at` and commits **once, at the end of the whole batch** — not per-event. If the dispatcher process crashes after some/all `enqueue_job` calls have already had their Redis side effect but before that single commit, `dispatched_at` was never persisted; on restart, the same events are picked up and **re-enqueued with new (non-deterministic) job ids**, since `events.py:54`'s `enqueue_job` call passes no `_job_id`. This is genuine at-least-once delivery with real duplicate-delivery risk, not exactly-once as the dispatcher's own docstring claims. Concretely: `knowledge_item.created` dispatches twice → two independent `agent_runs`, two duplicate `content_items` drafts for the same source, both independently reviewable and approvable, each capable of triggering its own live Reddit post if a reviewer doesn't notice they're duplicates. **Directly contradicts `docs/jobs/BACKGROUND_JOBS.md:75-77`**, which describes this exact scenario as already handled via a `(domain_event.id, subscriber_key)`-keyed idempotent enqueue that does not exist in the code. | `backend/app/core/dispatcher.py:30-43`, `backend/app/jobs/events.py:54` | **High** |
| R2 | Inside `publish_content_item`, the plugin's `publish()` call (which has a real external side effect — posting to Reddit) happens at line 99; the DB row updates that record success are only `flush()`ed, not `commit()`ted, until line 160. If the worker process is killed between those two points (OOM, deploy restart, network partition to Postgres), the whole transaction rolls back and the item is left `approved` as if nothing happened. If that same job is later re-run (a manual `retry-publish`, or a redelivery per R1's pattern applied to a hypothetical future crash-recovery path), `publish_content_item` sees `status == approved` and calls `plugin.publish()` again — a second live Reddit comment, since neither `content_publish_attempts` (non-unique index only) nor Reddit's own API is given any client-side idempotency token to prevent it. This is a narrow window (a process crash at exactly the wrong instant), not a routine occurrence, but the blast radius (a real, irreversible external post, duplicated) is high. | `backend/app/jobs/publish.py:99-160` | **Medium-High** (narrow window, high-impact outcome) |
| R3 | `trigger_agent_run`'s `enqueue_job` call has no `_job_id`, unlike the publish job's deterministic one — a network retry or double-click genuinely queues two independent agent runs (duplicate LLM spend, possible duplicate drafts), not just a theoretical risk. | `backend/app/api/v1/agent_configs.py:60-87` | **Medium** |
| R4 | The publish job's own idempotency (deterministic `_job_id = f"publish-{item_id}"`) is correctly implemented and does prevent a concurrent duplicate *enqueue* — verified sound. This is the one idempotency mechanism in the codebase that works exactly as documented. | `backend/app/api/v1/content_items.py:45-50` | **Confirmed clean** |

### 3.3 The self-check dead end

`ContentDraftClient.submit_for_review` leaves a draft permanently at `status=draft` with no
audit row if the self-check fails, and nothing anywhere queries, alerts on, or surfaces this —
confirmed by grep across the codebase. In practice, discovering a failed self-check today
requires manually querying `content_items WHERE status='draft'` or
`agent_runs.summary->>'self_check_passed'`. This was a known, explicitly-scoped-out gap when
Phase 2C shipped (see `docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md` §5), not a
surprise — restated here because "silent, permanent, invisible loss of a drafted (LLM-cost-
incurring) reply" is a genuine reliability property, not just a UX nicety. **Medium-High.**

### 3.4 Plugin call resilience

`plugins/reddit/client.py` correctly normalizes every failure mode (timeout, connection error,
non-2xx, malformed JSON, Reddit's HTTP-200-but-logical-error shape) into a single
`RedditAPIError` — but performs **no internal retry or backoff of its own**, deferring entirely
to "the outer job's retry policy." Given §3.1, that outer policy doesn't currently retry at
all, so today **a single transient Reddit 5xx or timeout causes an immediate, permanent,
single-attempt failure** with no automatic recovery — the opposite of a retry storm, but a real
gap once combined with §3.1's finding.

### 3.5 Confirmed clean

- The transactional outbox pattern (`EventPublisher.publish` → `flush()`, not `commit()`,
  always called before the enclosing method's own `commit()`) is genuinely atomic with the row
  it describes in every call site reviewed — the *outbox* half of the design holds; it's the
  *dispatch* half (§3.2, R1) that has the gap.
- The global exception handlers (`backend/app/core/errors.py:89-126`) catch every exception
  type reachable from an HTTP request handler — no raw 500/stack trace ever reaches an API
  client. This does not extend to Arq worker processes, which is architecturally consistent
  (their durable record is the `agent_runs`/`content_publish_attempts` row, not an HTTP
  response), not a bug.

---

## 4. Scalability Review

At current (single-project, solo-operator) scale, nothing here is on fire. Several of these
findings will start mattering well before Phase 3's "second project" milestone, though — two of
them (S-4 and S-5 below) are already true today, not future risks.

| # | Finding | File(s) | Severity |
|---|---|---|---|
| SC1 | `content_items` and `knowledge_items` list queries both filter by an index that doesn't include the `ORDER BY` column (`idx_content_items_project_status` is `(project_id, status)`; both list methods sort by `created_at`/`discovered_at DESC` with no covering index). Degrades toward a full sort as either table grows past what fits comfortably in a sort buffer. | `database/schema.sql:306`, `backend/app/repositories/content_repository.py:22-28`, `knowledge_repository.py:43-49` | **Medium** |
| SC2 | Default SQLAlchemy async engine pooling (`pool_size=5`, `max_overflow=10` → 15 connections/engine) is unmodified, and a **separate engine is created per process** — the FastAPI app, the scheduler, and each of four Arq worker types. Counting only what `docker-compose.yml` already declares (`worker-agents` at `replicas: 2`, plus one each of backend/scheduler/worker-events/worker-publish) yields **~90 connections against Postgres's default `max_connections=100`**, before the not-yet-composed `worker-oauth-refresh` is even added. No PgBouncer or pool tuning exists anywhere in the stack. This is not a distant Phase 3 concern — it's one `replicas:` bump away from exhausting Postgres's connection limit today. | `backend/app/core/db.py:21-27`, `docker/docker-compose.yml:93` | **High** |
| SC3 | The Reddit plugin's rate limiter (`RateLimiter(capacity=60, refill_rate=1.0)`) is a single **module-level, in-process** token bucket — it does not coordinate across processes and resets on restart. `docker-compose.yml` already runs `worker-agents` at 2 replicas, meaning Conversation Finder's Reddit search traffic can already exceed Reddit's real rate limit by up to 2× today, not just under future horizontal scaling. This is self-documented as a known limitation in `plugins/_shared/rate_limit.py`'s own comments, not a silent bug — but it's live today, not deferred. | `plugins/reddit/plugin.py:19`, `plugins/_shared/rate_limit.py:32-40` | **Medium** |
| SC4 | No LLM call concurrency throttle exists anywhere in `app/core/llm/`. A burst of `knowledge_item.created` events dispatches straight into simultaneous Claude API calls, bounded only by Arq's default `max_jobs=10` per worker process — a coincidental bound from job-queue defaults, not a deliberate cost/rate control, and it scales linearly with worker replica count exactly like SC3. | `backend/app/core/llm/anthropic_provider.py`, `backend/app/jobs/events.py` | **Medium** |
| SC5 | `domain_events`, `audit_log`, `content_publish_attempts`, and `agent_runs` are all deliberately append-only with no delete path (a documented design choice, not an oversight) — but there is genuinely zero retention/archival/partitioning code anywhere, only aspirational prose in `docs/scalability/SCALABILITY.md`. The one specific performance claim that matters today — that the `dispatched_at IS NULL` partial index keeps the dispatcher's hot path cheap regardless of total table size — is independently verified true. General table bloat (autovacuum overhead, backup/dump time) has no mitigation, correctly deferred per the docs' own framing, but worth tracking before these tables reach real production volume. | `database/schema.sql` | **Low, correctly deferred** |
| SC6 | `knowledge_items.embedding` has a real HNSW index already built (`idx_knowledge_items_embedding`) despite nothing populating the column yet — a non-issue today (an index over all-NULL vectors is nearly free) and purely future-facing once an embedding pipeline exists. | `database/schema.sql:241` | **Informational** |
| SC7 | No N+1 query risk found — no lazy-loaded relationships exist on any of the high-traffic models (`ContentItem`, `KnowledgeItem`, `DomainEvent`, `AgentRun`, `PluginConnection` all use raw FK columns, not `relationship()`). | `backend/app/models/*.py` | **Confirmed clean** |

---

## 5. Operational Readiness Review

| # | Finding | File(s) | Severity |
|---|---|---|---|
| O1 | `GET /health` unconditionally returns `{"status": "ok"}` with no DB or Redis connectivity check whatsoever. Any orchestrator (Docker healthcheck, load balancer, uptime monitor) wired to this endpoint will report healthy even with Postgres or Redis completely unreachable. | `backend/app/api/v1/health.py:10-12` | **High** |
| O2 | **No backup automation, WAL archiving, or disaster-recovery procedure exists anywhere in the repository** — only aspirational prose in `docs/deployment/DEPLOYMENT.md` describing a plan. For a Postgres instance holding the sole copy of encrypted OAuth credentials and the entire knowledge base, this means **total, unrecoverable data loss on any disk/volume failure**, with no runbook even for a manual restore. | grep-confirmed absent repo-wide | **Critical** |
| O3 | No service in `docker-compose.yml` has a `restart:` policy. A crashed backend or worker container simply stays dead until a human notices and intervenes — directly undermining the "runs unattended every morning" design goal stated throughout `ROADMAP.md`. | `docker/docker-compose.yml` (grep-confirmed absent) | **High** |
| O4 | Docker healthchecks exist for Postgres and Redis only — none of backend, scheduler, or any of the four worker types have one. Combined with O3, a hung (not crashed) process — a deadlocked event loop, a stuck Arq job — is invisible to the orchestration layer indefinitely. | `docker/docker-compose.yml:24-38` vs. the rest of the file | **Medium** |
| O5 | `docker-compose.yml`'s own header comment admits the compose stack has never actually been run end-to-end (`docker compose build` has not been executed against it). This means the entire deployment path described in `docs/deployment/DEPLOYMENT.md` is unverified, not just undertested. | `docker/docker-compose.yml:4-11` | **High** (informational but material) |
| O6 | `POSTGRES_PASSWORD` has a hardcoded fallback default (`growthos_dev`) directly in the compose file's `environment:` substitution (`${POSTGRES_PASSWORD:-growthos_dev}`). If an operator forgets to set it in `.env`, the database silently boots with a known, publicly-visible-in-this-repo password, and the substituted value is visible via `docker inspect`. | `docker/docker-compose.yml:18` | **Medium** |
| O7 | No automated migration step exists anywhere — not on container startup (`Dockerfile.backend`'s CMD is bare `uvicorn`, no `alembic upgrade`), and not in any CI/CD script (no `.github/` directory exists at all). The "manual, deliberate step" `docs/deployment/DEPLOYMENT.md` describes has no executable form anywhere — it is prose only, which makes it forgettable in a real deploy. | `docker/Dockerfile.backend`, repo-wide (no `.github/`) | **High** |
| O8 | Zero observability tooling exists in code — grep for `opentelemetry`/`prometheus`/`otel`/`sentry` across the entire backend and every agent/plugin package returns no matches. `docs/observability/OBSERVABILITY.md` describes a full OTel + Prometheus/Grafana stack with specific alerts; **100% of it is aspirational**. The doc itself is honest about being a forward-looking workstream, but a reviewer evaluating "is this production ready" should know the gap is total, not partial. | grep-confirmed absent repo-wide | **High** |
| O9 | No error-tracking SDK (Sentry or equivalent) is wired into either the FastAPI app or any Arq worker, despite `docs/deployment/DEPLOYMENT.md` itself calling worker error visibility "a production-readiness requirement, not a nice-to-have." Today, a worker-side exception's only home is process stdout logs. | grep-confirmed absent | **Medium** |
| O10 | `docs/deployment/DEPLOYMENT.md` does not address TLS/HTTPS termination (no reverse proxy — nginx/traefik/caddy — in `docker-compose.yml` or the doc), domain/DNS setup, or process supervision outside Docker. As written, this document is an architecture-intent statement, not a runbook a new operator could follow to stand up a real internet-facing deployment. | `docs/deployment/DEPLOYMENT.md` | **Medium-High** |
| O11 | Redis has no persistence volume configured (`appendonly`/AOF or an RDB volume) in `docker-compose.yml` — a Redis restart loses in-flight/queued Arq jobs. Since Postgres's `domain_events` table is the real source of truth for the event-driven half of the system, undispatched work is recoverable on the next dispatch cycle, but anything already dequeued and mid-flight in a worker at restart time is lost with no compensating record. | `docker/docker-compose.yml:30-38` | **Medium** |
| O12 | **`app/jobs/oauth_refresh.py` — a real, tested, fully-implemented periodic sweep that refreshes about-to-expire OAuth tokens — has no corresponding service in `docker-compose.yml` at all.** Confirmed by grep: the module exists with its own `WorkerSettings`, but no `worker-oauth-refresh` (or cron-equivalent) entry exists anywhere in the compose file. This means the one mechanism designed to stop a connected Reddit account's token from silently expiring never actually runs in the deployment this project ships — every connection will eventually degrade to `expired` (requiring manual reconnect) purely because nothing ever invoked the refresh it was built for, not because of any real token problem. | grep-confirmed absent from `docker/docker-compose.yml`; job itself is real at `backend/app/jobs/oauth_refresh.py` | **High** |

### Confirmed clean

- Structured JSON logging genuinely goes to stdout in production mode and is controllable via
  a `LOG_LEVEL` env var — this part of the logging story is real, not aspirational, and would
  work correctly with any standard container-log-tailing aggregator.
- `Settings()` fails loudly and immediately at process startup if any required secret
  (`secret_key`, `credential_master_key`, `anthropic_api_key`, `database_url`, `redis_url`) is
  missing — no insecure silent-boot path exists. (`openai_api_key` is oddly also required
  despite OpenAI having no implementation yet — an operational annoyance, not a security issue.)
- The two Phase 2C migrations (`ALTER TYPE ... ADD VALUE`, and the new
  `content_publish_attempts` table) carry no meaningful lock risk on Postgres 16 — verified,
  not assumed.
- `.env` is correctly gitignored; `.env.example` contains no real secret values.
- The embedded-Postgres test harness (`pgserver`) includes real `pgvector` support, so schema
  parity with the Postgres 16 + pgvector image used in `docker-compose.yml` is reasonable —
  though no test exercises real connection-pool behavior under concurrent load, since every
  test runs inside one outer transaction rolled back via savepoints. No load/performance
  testing tooling (Locust, k6, or otherwise) exists anywhere in the repository.

---

## 6. Top-priority issues before first production deployment

Ranked by (likelihood × blast radius), not by section. "Fix" is a direct, scoped description,
not a redesign — every item below is a targeted change to existing code, consistent with this
review's brief not to recommend redesigns.

| Priority | Issue | Why it's here | Fix |
|---|---|---|---|
| 1 | **Retry is silently non-functional across every background job** (§3.1) | Defeats an explicit Phase 2C requirement platform-wide; every transient failure (LLM blip, Reddit 5xx, network hiccup) becomes a permanent one-shot failure today | Raise `arq.worker.Retry(defer=...)` instead of a plain exception at the four re-raise sites in `publish.py`, `agent_runs.py`, `events.py`, and wherever `oauth_refresh.py` intends the same |
| 2 | **No backups / disaster recovery** (O2) | Total, unrecoverable data loss (encrypted credentials + entire knowledge base) on any disk failure, with zero mitigation today | Add automated `pg_dump`/WAL-archiving to the deployment, even a simple daily cron to off-instance storage, plus a written restore drill |
| 3 | **Health check is a no-op** (O1) | Every orchestration/monitoring decision built on top of it (restart-on-failure, load-balancer routing, uptime alerts) is blind to real outages | Add DB `SELECT 1` and Redis `PING` checks to `/health`, return 503 on failure |
| 4 | **No `restart:` policy anywhere in `docker-compose.yml`** (O3) | A crashed process (not a hung one — an actual crash) stays down until a human notices, contradicting the "unattended" design goal | Add `restart: unless-stopped` to every service |
| 5 | **Connection-pool math is already near the edge** (SC2) | One more `replicas:` bump on any worker type exhausts Postgres's default `max_connections=100`, and the failure mode (connection refusals) is confusing to diagnose under pressure | Explicitly set `pool_size`/`max_overflow` per process type, or introduce PgBouncer before adding more worker replicas |
| 6 | **Event dispatch can double-deliver** (R1) | Duplicate `agent_runs`, duplicate drafts, duplicate LLM spend, and — if a reviewer doesn't notice two near-identical drafts — a real risk of two independent Reddit posts for the same source thread | Add a deterministic `_job_id` (e.g. `f"{event.id}-{subscriber_key}"`) to the `enqueue_job` call in `events.py:54`, matching the pattern the publish job already uses correctly |
| 7 | **No API-level rate limiting, especially on login** (S1) | Directly contradicts `docs/security/SECURITY.md`'s own stated mitigation; credential-stuffing against a real user's account is unmitigated today | Add a rate-limit middleware (even a simple in-memory/Redis-backed token bucket per IP+account) in front of `/auth/login` at minimum |
| 8 | **No end-to-end verification the deployment path even works** (O5) | The entire `docker-compose.yml` stack has never been run — every operational assumption in this review's §5 rests on an unverified foundation | Actually run `docker compose build && docker compose up` against a clean environment once, fix whatever breaks, before this is anyone's first production deploy |
| 9 | **CSRF protection is claimed but not implemented** (S2) | A false security claim in both code docstrings and `docs/security/SECURITY.md` — someone relying on the stated protection is unprotected | Either wire the existing CSRF cookie into an actual header-comparison check on state-changing routes, or remove the claim and rely explicitly on `SameSite=Lax` (document the choice either way) |
| 10 | **`retry-publish`'s narrow duplicate-post window** (R2) | Low-frequency but high-impact (an irreversible, duplicated public post) | Make the plugin-call-then-record sequence transactionally safer — e.g. commit the attempt record immediately after the plugin call returns, before any other work, narrowing the crash window as far as possible; a true fix needs a durable "did this already post" check before calling `plugin.publish()` again |
| 11 | **The OAuth token-refresh worker is never actually deployed** (O12) | Every connected Reddit account will eventually and needlessly degrade to `expired`, defeating the whole point of building the refresh sweep, purely because nothing invokes it | Add a `worker-oauth-refresh` service to `docker-compose.yml` (or fold it into an existing periodic-job runner), matching the pattern already used for the other three worker types |
| 12 | **`POSTGRES_PASSWORD` has a public, guessable fallback default** (O6) | An operator who forgets to set it boots a database with a password visible in this very repository | Remove the fallback; fail the compose stack loudly if unset in a non-local environment |
| 13 | **Zero observability** (O8, O9) | Not itself a bug, but means every other issue in this review is currently undetectable in production without someone manually checking | At minimum: wire a basic Sentry (or equivalent) integration into the FastAPI app and Arq workers before first real usage — full OTel/Prometheus can follow later, but *some* automatic error visibility is a launch blocker, not a nice-to-have |

Items 1–6 are the genuine launch blockers — they combine realistic likelihood with either
data loss, duplicate real-world side effects, or a documented security control that doesn't
exist. Items 7–13 should be closed before onboarding a second real (non-owner) user, but a
careful solo operator could reasonably launch with them open and closed shortly after.

---

## 7. Nice-to-have improvements after launch

These are genuine gaps but none of them risk data loss, a security breach, or a duplicated
real-world action — they degrade quality, cost, or developer experience, not correctness.

- **Master-key derivation** — swap the single SHA-256 pass for a real KDF (HKDF is sufficient
  given the input is already a high-entropy secret, not a human password) (S3).
- **Session revocation** — add a minimal server-side denylist/session-store so one compromised
  session can be revoked without rotating the global secret key (S4).
- **Account-enumeration timing gap** in `authenticate()` — normalize response timing regardless
  of whether the account exists (S6).
- **Role enforcement** — before any invite/multi-user feature ships, wire `MembershipRole`
  into `require_project_access`/`require_org_access` so "member" actually means something
  narrower than "owner" (S7).
- **Dependency lockfile** — pin exact versions via `pip-compile`/`uv lock` for reproducible
  builds (S8).
- **List-endpoint pagination gaps** — add `limit`/`offset` to `agent-configs` and
  `plugin-connections` list routes, and add `Idempotency-Key` header support to
  `.../runs/trigger` at minimum (§1, R3).
- **Missing composite indexes** — `(project_id, status, created_at DESC)` on `content_items`,
  equivalent on `knowledge_items` (SC1).
- **LLM/plugin call concurrency throttle** — a deliberate semaphore instead of relying on Arq's
  incidental `max_jobs` default (SC4).
- **Cross-process rate limiting** for the Reddit plugin's token bucket — move it to
  Redis-backed so it coordinates across worker replicas instead of resetting per-process
  (SC3).
- **Redis persistence** — add an AOF/RDB volume so a Redis restart doesn't silently drop
  in-flight job state (O11).
- **API response envelope and cursor pagination** — the two `docs/api/API_DESIGN.md`
  conventions that have never been implemented; a genuine cross-cutting change worth doing once,
  consistently, exactly as that doc itself already recommends deferring it until deliberate.
- **CORS middleware**, added deliberately (allowlisted origins, not wildcard) at the moment a
  separate-origin frontend is actually introduced — not before.
- **Retention/partitioning story** for the append-only tables, once real volume approaches a
  scale where it matters (SC5) — correctly not urgent today.

---

## 8. Recommended Phase 3 roadmap

`ROADMAP.md` currently defines **Phase 3** as "second project + deferred agents" — onboarding
a second SaaS business to prove nothing is hardcoded to the first one. This review recommends
**not** starting that phase next. Onboarding a second real customer/project before closing
§6's launch blockers means a second tenant is exposed to the same data-loss, duplicate-post,
and blind-outage risks as the first, doubling the blast radius before any of it is fixed.

**Recommendation: insert a short, explicitly-scoped "Phase 2D — Production Hardening" between
the current state and `ROADMAP.md`'s existing Phase 3**, covering exactly and only §6's twelve
items plus the tests that prove each one is actually fixed (a regression test for the retry
bug in particular — e.g. assert that a job which raises does get a second attempt — since this
review found the *absence* of such a test is exactly how the bug shipped unnoticed through
Phase 2C's own "test results" sections). This is a documentation/roadmap change for the user
to decide on and make, not something to implement as part of this review.

Suggested shape, in priority order:

1. **Reliability fixes** — items 1, 6, 10 from §6 (retry mechanism, event dispatch dedup,
   publish-worker crash window). These are the ones this review is most confident are simple,
   contained, low-risk changes to existing code, not architecture changes.
2. **Operational floor** — items 2, 3, 4, 8, 11, 12 (backups, real health check, restart
   policies, an actual verified `docker compose up`, deploy the OAuth refresh worker, remove
   the weak default password). Nothing here is novel engineering; it's the minimum a system
   needs before "runs unattended" is a true statement rather than an aspiration.
3. **Security floor** — items 7, 9 (login rate limiting, resolve the CSRF claim one way or the
   other) plus S3/S4 from §7 if time allows.
4. **Baseline observability** — item 13 (a minimal error-tracking SDK). Full OTel/Prometheus
   per `docs/observability/OBSERVABILITY.md` can genuinely wait; *some* automatic visibility
   into production errors cannot.
5. **Only then**, resume `ROADMAP.md`'s existing Phase 3 (second project) — at which point the
   platform's operational floor is trustworthy enough that a second tenant's risk profile
   matches the first tenant's, rather than compounding an already-open set of gaps.

This ordering does not change anything about `ROADMAP.md`'s Phase 2 (full agent roster) or the
existing Phase 3 definition's actual content — it only recommends where to insert this review's
findings in the sequence, and is offered as a recommendation for the user to accept, adjust, or
reject, not as a change already made to the roadmap document.
