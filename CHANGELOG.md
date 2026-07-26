# Changelog

All notable changes to GrowthOS are documented in this file, in reverse chronological order.
Versions before Phase 4 (multi-tenant activation) are development milestones, not public
releases — see `ROADMAP.md` for the phase plan and `ARCHITECTURE.md` for the system design
each version builds on.

## [0.7.0] - 2026-07-26 - Production Hardening (Phase 2D)

**Tag:** `v0.7.0-production-hardening`. Full reports:
`docs/reviews/PRODUCTION_READINESS_REVIEW.md` (the audit) and
`docs/reviews/PRODUCTION_HARDENING_REPORT.md` (what was fixed).

An adversarial production-readiness review of the entire platform (foundation through Phase
2C) surfaced one platform-wide correctness bug and a cluster of operational gaps that would
turn any transient failure into either silent data loss or a permanent, invisible outage. This
release fixes every Critical/High-severity finding, in priority order, with a regression test
for each one — no architecture changes, no ADRs touched.

### Fixed
- **Retry was silently non-functional across every background job.** Every job set
  `max_tries = 3`, but Arq only retries a job that raises its own `arq.worker.Retry` — a plain
  exception (what every job actually raised) is a permanent failure after one attempt,
  regardless of `max_tries`. `app/core/job_retry.py` (new) is now the one place the correct
  exception type and a shared exponential-backoff formula live; `publish.py`, `agent_runs.py`,
  and `events.py` all raise it correctly now.
- **Event dispatch could double-deliver.** `EventDispatcher.dispatch_pending` now commits
  `dispatched_at` per event instead of once per batch, and `app/jobs/events.py`'s enqueue call
  carries a deterministic job id (`event.id` + `agent_key`) — a dispatcher crash-and-redispatch
  no longer re-processes an already-handled event/subscriber pair.
- **A narrow crash window in the publish worker could duplicate a real Reddit post.** Before
  calling a plugin, the job now checks for a prior successful `content_publish_attempts` row
  and reconciles instead of posting again if one exists.
- **`GET /health` always returned `{"status": "ok"}`** regardless of database or Redis
  reachability. Now checks both and returns 503 with per-check detail on failure.
- **Nothing verified a connected database was at the expected migration revision.**
  `app/core/migration_check.py` (new) — every process now refuses to start against a stale
  schema instead of failing confusingly at the first query touching new schema.
- **Zero error-tracking existed anywhere.** `app/core/observability.py` (new) — an optional,
  `SENTRY_DSN`-gated integration wired into the API and every background worker; a no-op if
  unset.
- **Login had no rate limiting**, despite `docs/security/SECURITY.md` claiming it did.
  `app/core/rate_limit.py` (new, generic token-bucket) now gates `POST /auth/login` both per
  source IP and per account.
- **The OAuth token-refresh worker (`app/jobs/oauth_refresh.py`) was a real, tested job that
  nothing ever ran.** `docker/docker-compose.yml` gained its missing service definition; the
  non-Docker run command is now documented in `docs/deployment/DEPLOYMENT.md`.
- **The connection-pool budget was unmanaged** — six processes at default pooling already
  summed to ~90 connections against Postgres's default `max_connections=100`. `Settings.
  db_pool_size`/`db_max_overflow` (new, defaulting to prior implicit behavior) make it
  explicit and tunable.
- Several docs/docstrings that made false claims (retry, idempotency, login rate limiting,
  the CSRF double-submit check) were corrected to describe actual behavior — see
  `docs/reviews/PRODUCTION_HARDENING_REPORT.md` §1.10.

### Added
- `docs/deployment/DEPLOYMENT.md`: a "Non-Docker deployment" section (this project's actual
  mode of operation) with concrete run commands for every process, a concrete `pg_dump`/
  `pg_restore` backup runbook, a process-supervision requirement (generic, not
  systemd-specific), and TLS/domain guidance — all previously undocumented gaps.
- `docs/scalability/SCALABILITY.md`: a "Database connection budget" section with the actual
  connection-count formula and concrete next steps before adding worker replicas.
- 25 new tests (400 total, up from 375) — one regression test per bug fixed.

### Deliberately not fixed this phase (see the hardening report §4 for the full list)
Medium/low-severity findings — CSRF verification, the master-key KDF, session revocation,
`MembershipRole` enforcement, a dependency lockfile, missing composite indexes, and others —
plus backup/process-supervision *automation* specifically (documented as a manual procedure
by explicit decision, since the real hosting target isn't chosen yet). None of these were
required to safely resolve a Critical/High-severity issue.

## [0.6.0] - 2026-07-26 - Approval & Publishing Workflow (Phase 2C)

**Tag:** `v0.6.0-approval-publishing`. Full reports:
`docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md` and
`docs/reviews/PUBLISHING_WORKFLOW_IMPLEMENTATION_REPORT.md`.

Closes the loop the first time: a Content Agent draft can now be reviewed, approved or
rejected or archived by a human, and — once approved — actually published through the Reddit
plugin, with an audit row for every transition and a durable per-attempt publish history.
Every state change enforces ARCHITECTURE.md §8's state machine and its optimistic-concurrency
`version` guard.

### Added
- `app/services/content_approval.py` — `ContentApprovalService` (`approve`/`reject`/
  `archive`), each a single atomic `UPDATE ... WHERE status IN (...) AND version = :expected`
  that does the state-transition check and the concurrency check in one round trip; a
  zero-row result raises `InvalidStateTransition` (409), covering both an illegal transition
  and a stale `version` with the same guard.
- `app/services/content_self_check.py` — `run_self_check()`: a length limit and a
  case-insensitive banned-phrase filter, the "agent's own self-check" ARCHITECTURE.md §8 has
  always specified. Content-type-agnostic; duplicate-content detection is explicitly not
  implemented (future work).
- `ContentDraftClient.submit_for_review` — the missing auto-advance step: runs the self-check
  and, if it passes, moves the item `draft → pending_review` and writes an audit row.
  Deliberately a separate method from `create_draft` (unchanged, still only ever writes
  `draft`) so each method's guarantee stays precise while the agent's overall workflow matches
  "always created in draft, immediately auto-advanced" as documented.
- `app/jobs/publish.py` — real `publish_content_item`: resolves the project's `Publishable`
  plugin via `PluginRegistry.get`, calls `plugin.publish(item)`, records a
  `content_publish_attempts` row for every attempt (success or failure), and on success
  publishes a `content_item.published` domain event. On failure, sets `publish_error` and
  raises to trigger Arq's retry (up to 3 attempts) — the item stays `approved`, never
  auto-transitioned, since a failed publish is not a rejection.
- `app/repositories/content_repository.py` — `ContentPublishAttemptRepository`.
- API: `POST .../content-items/{id}/approve` (enqueues the publish job with a deterministic
  `_job_id`), `.../reject` (`reason` required), `.../archive` (`reason` optional — the fifth
  status, not in the original 4-state diagram), `.../retry-publish` (re-enqueues the same
  idempotency-keyed job for a previously-exhausted-retries item), `GET .../publish-attempts`
  (the durable publish history).
- 41 new tests: `test_content_approval_service.py` (10), `test_publish_worker.py` (7),
  `test_content_self_check.py` (9), plus additions to `test_content_items_api.py` (+9),
  `test_content_drafts_client.py` (+3), `test_run_agent_for_event_job.py` (+1), and
  `agents/content_agent/tests/test_agent.py` (+2). Full suite: 269 backend tests + 106
  agents/plugins tests = 375 total, all passing.

### Schema
- `content_item_status` gained `archived` — a genuine fifth terminal state, not an alias for
  `rejected`, added via its own migration (`ALTER TYPE ... ADD VALUE`, since Postgres can't use
  a freshly-added enum value in the same transaction that added it).
- New table `content_publish_attempts` — one row per publish *attempt*, distinct from the
  single current-state `content_items.publish_error` column, for real publish history and
  retry visibility.

### Architecture note
- Building `ContentApprovalService` against ARCHITECTURE.md §8 exposed a genuine gap: Phase
  2B's Content Agent (per that phase's own explicit scope) left every draft in `draft`
  forever, with nothing to promote it to `pending_review` — the only state `approve`/`reject`
  can act on per the frozen design. Per this phase's instruction to stop and ask before a
  breaking change, this was resolved by user decision rather than by guessing: build the
  missing auto-advance step now (rather than having the service accept `draft` directly, which
  would have deviated from the documented state machine), and add `archived` as a real new
  enum value (rather than aliasing it to `rejected`). See ARCHITECTURE.md §8's implementation
  note for the full reasoning.

### Scoping notes (see the implementation reports for full reasoning)
- **No automatic publishing without approval, no scheduling.** The publish job's only trigger
  is the `approve` transition (or a manual `retry-publish`) — nothing else ever enqueues it.
- **No bulk approve, no frontend, no LinkedIn/X/Slack/email.** Out of scope for this phase; see
  `ROADMAP.md`.
- **Code-complete, not yet real-world-verified.** Every step of discover → draft → approve →
  publish now has a real, tested implementation, but nothing has exercised it against an
  actual connected Reddit account with a real Anthropic API key.

## [0.5.0] - 2026-07-25 - Content Agent (Phase 2B)

**Tag:** `v0.5.0-content-agent`. Full report:
`docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md`.

The first subscription-triggered agent and the first real LLM consumer: reacts to
`knowledge_item.created`, drafts one Reddit reply per triggering item via Claude, and
persists it as a `content_items` row — always `status="draft"`, never advanced further.

### Added
- `backend/app/core/llm/` — the generic `LLMProvider` interface (ADR 0004) plus
  `AnthropicProvider`, the first (and so far only) implementation.
- `agents/content_agent/` — `agent.py`, `config.py`, `prompts/reddit_reply.py` (system
  prompt, response-JSON parsing), `subscriptions.py`.
- `app/services/content_drafts.py` — `ContentDraftClient`, `AgentContext.content`'s first
  concrete implementation.
- `app/repositories/content_repository.py` — `ContentItemRepository`.
- API: `GET /projects/{project_id}/content-items[/{id}]` (drafts, read-only).
- 44 new tests (30 in `agents/content_agent/tests/`, 14 in `backend/tests/`).

### Changed
- `app/jobs/events.py` — `run_agent_for_event` now has a real body (was a placeholder since
  Phase 1): loads the triggering event, auto-provisions an `agent_configs` row if needed,
  builds a real `AgentContext`, runs the agent, records the outcome — the subscription-
  triggered counterpart to `run_scheduled_agent`.
- `agents/_shared/base.py` — `AgentContext.llm` tightened from `object` to the concrete
  `LLMProvider`; added `trigger_payload` (the triggering event's payload, for subscription-
  triggered agents) and `content` (`ContentDraftClient`).
- `app/repositories/agent_repository.py` — added `AgentConfigRepository.get_or_create`,
  used by both the on-demand trigger endpoint and the event-triggered job runner.

### Schema
- `knowledge_items` gained `title`, `body_excerpt`, `platform_metadata` — grounding text and
  an opaque plugin-specific reference, captured by Conversation Finder at discovery time.
  Nothing needed these until Content Agent did; both are null for any row discovered before
  this migration.
- `content_items` gained `confidence`, `reasoning`, `evidence` — the drafting agent's own
  self-assessment, attached to every draft.

### Scoping notes (see the implementation report for full reasoning)
- **Reddit replies only.** No outreach drafts, no article drafts, no other platform — a
  `knowledge_item` from any other platform is skipped, not an error.
- **No `buying_intent` subscription filter.** Nothing populates that field yet (Conversation
  Finder has no LLM integration), so `content_agent` subscribes unconditionally and gates
  relevance inside `run()` against the triggering item's `confidence` instead.
- **No self-check, no promotion to `pending_review`.** Every draft stays exactly at
  `status="draft"` — the approval workflow (Phase 2C) doesn't exist yet, and this task's
  instructions are explicit that a draft must not advance without one.
- **Structured output via prompt + parse, not a provider-specific mechanism.** `LLMProvider`
  is a plain-text completion API; `agents/content_agent/prompts/reddit_reply.py` asks for a
  JSON response and parses it, matching ADR 0004's "common subset" trade-off.

## [0.4.0] - 2026-07-25 - Conversation Finder (Phase 2A)

**Tag:** `v0.4.0-conversation-finder`. Full report:
`docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md`.

The first agent to actually run: a schedule-triggered discovery agent that searches every
project-connected `Searchable` plugin, ranks results with a deterministic keyword-relevance
score, deduplicates by URL, persists survivors to the knowledge base, and announces each new
discovery with a `knowledge_item.created` domain event.

### Added
- `agents/conversation_finder/` — the agent itself (`agent.py`, `config.py`, `ranking.py`,
  `subscriptions.py`), the first real package built against the Phase 1 agent contract.
- `app/services/knowledge_base.py` — `KnowledgeBaseClient`, `AgentContext.knowledge_base`'s
  first concrete implementation (dedup-then-upsert by URL).
- `app/core/agent_registry.py` — loads an installed agent by key for execution, mirroring
  `plugin_registry.py`'s plugin-loading convention.
- `app/services/agent_config.py` — create/update a project's `agent_configs` row, validated
  against the target agent's own config schema.
- `app/repositories/knowledge_repository.py` — `KnowledgeItemRepository`.
- API: `GET/PUT /projects/{project_id}/agent-configs[/{agent_key}]`,
  `POST .../agent-configs/{agent_key}/runs/trigger`, `GET .../agent-configs/{agent_key}/runs`,
  `GET /projects/{project_id}/knowledge-items`.
- 54 new tests (27 in `agents/conversation_finder/tests/`, 27 in `backend/tests/`).

### Changed
- `app/jobs/agent_runs.py` — `run_scheduled_agent` now has a real body (was a
  `logger.info(...)` placeholder since Phase 1): loads the agent config, builds a real
  `AgentContext`, runs the agent, records the outcome as an `agent_runs` row.
- `agents/_shared/base.py` — `AgentContext.knowledge_base` tightened from `object` to the
  concrete `KnowledgeBaseClient`; added `agent_run_id: uuid.UUID | None = None`.
- `app/api/deps.py` — added `get_arq_redis`, a lazily-created/cached Arq connection pool
  (not eager at app startup, so routes that never enqueue a job impose no live-Redis
  dependency on tests or requests).

### Scoping notes (see the implementation report for full reasoning)
- **No LLM integration** — none exists yet in this codebase. `knowledge_items.problem`/
  `industry`/`product`/`pain_point`/`buying_intent`/`suggested_*` stay at schema defaults for
  every row this agent writes; `confidence` is a deterministic keyword-match score, not an
  LLM's judgment. A future enrichment pass (or Content Agent itself) fills these in.
- **No new database migration** — `knowledge_items`, `agent_configs`, and `agent_runs` were
  already part of the Phase 0/1 schema; this is the first agent to write to two of them for
  real.
- **Per-plugin search config (e.g. Reddit's subreddit allowlist) stays on the plugin
  connection**, not duplicated into this agent's own config — one source of truth per
  ADR 0009.

## [0.3.1] - 2026-07-25 - Reddit Plugin

Full report: `docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md`.

The first real plugin (`plugins/dummy/` remains a discovery-mechanism test fixture, not a
real integration) — `Searchable` + `Publishable`, authenticated entirely through the generic
OAuth2 platform framework built in 0.3.0. Zero OAuth or Reddit-specific code anywhere outside
`plugins/reddit/`.

### Added
- `plugins/reddit/` — `manifest.py`, `client.py` (thin `httpx` wrapper, not PRAW — avoids
  duplicating the platform's own OAuth2 token lifecycle management), `plugin.py`, 31 tests.

### Changed
- `plugins/_shared/oauth.py` — added `OAuthProviderSpec.extra_token_headers`, a small,
  generic, additive extension needed because Reddit requires a `User-Agent` header even on
  its OAuth token endpoint (not just its data API). Empty-dict default; every existing
  manifest unaffected.
- `backend/app/core/oauth/client.py` — sends `extra_token_headers` on token-exchange and
  revoke requests.

## [0.3.0] - 2026-07-25 - Generic OAuth2 Platform

Envelope encryption (ADR 0010) and the generic, provider-agnostic OAuth2 framework
(ADR 0011) — built once real plugin credential storage was identified as the actual blocker,
ahead of any specific OAuth-capable plugin needing it.

### Added
- `app/core/crypto.py` — envelope encryption (AES-GCM) for `plugin_connections.credentials_encrypted`.
- `app/core/oauth/` — provider-agnostic authorize/exchange/refresh/revoke (`client.py`), PKCE
  (`pkce.py`), signed CSRF state tokens (`state.py`), the OAuth-flow exception hierarchy
  (`errors.py`).
- `app/services/oauth_connection.py`, `app/jobs/oauth_refresh.py` — connect/reconnect/
  disconnect orchestration and the periodic token-refresh sweep.
- `app/services/plugin_connection.py`, `plugin-connections` API — the piece needed to
  actually connect a finished plugin to a project (validated against the plugin's own
  `config_schema`).

## [0.2.0] - 2026-07-25 - Platform Foundation (Phase 1)

Full report: `PHASE_1_REPORT.md`.

FastAPI application, database schema, plugin/event core, background workers, and the testing
framework — built once, in the order the (now-archived) V1→V2 migration plan specified, not
built against V1 and reworked.

### Added
- `database/schema.sql` as SQLAlchemy 2.0 models (all 17 tables) + one Alembic migration.
- Plugin SDK (`plugins/_shared/`) — manifest, the four segmented capability Protocols
  (`Searchable`/`Publishable`/`WebhookReceivable`/`MetricsQueryable`), `plugins/dummy/` as the
  discovery-mechanism proof.
- Event core (`app/core/events.py`, `subscriptions.py`, `dispatcher.py`) — the transactional
  outbox, `EventPublisher`, `EventDispatcher`; `agents/_shared/` (the agent SDK — `Agent`
  Protocol, `AgentContext`, `AgentResult`, `EventSubscription`).
- Background workers (`app/jobs/`, Arq) and scheduler (`app/scheduler.py`, cron-driven
  `agent_configs` polling) — job *bodies* were placeholders; the queue plumbing (retries,
  separate queues per job category) was real from the start.
- Auth scaffold (register/login/logout/me), repository layer, dependency injection
  (`require_project_access` as the single tenant-isolation enforcement point).
- 67 tests against a real, embedded (Docker-free) Postgres via `pgserver`.

## [0.1.0] - 2026-07-25 - Architecture Freeze (Phase 0)

See `ARCHITECTURE_FREEZE.md`, `ARCHITECTURE.md`, `docs/architecture/LOCKED_DECISIONS.md`,
`docs/reviews/DESIGN_REVIEW.md`. Design documentation and a Principal Engineer design review
— no product code. Established the event-driven, plugin-capability-segmented, human-in-the-
loop architecture every subsequent version builds on without redesigning.
