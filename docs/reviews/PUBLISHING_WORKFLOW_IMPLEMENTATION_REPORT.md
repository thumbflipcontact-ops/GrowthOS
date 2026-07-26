# Publishing Workflow Implementation Report (Phase 2C, part 2 of 2)

**Date:** 2026-07-26
**Scope:** the publishing half of Phase 2C — the real publish worker, publishing through the
Reddit plugin, publish history, error handling and retry support, and background event
processing for the `approved → published` transition. This is the companion to
`docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md`, which covers
`ContentApprovalService` and the approve/reject/archive endpoints that trigger the work
described here.

---

## 1. Publishing Workflow Implementation Report

### What was built

```
backend/app/
├── jobs/publish.py                    publish_content_item(ctx, content_item_id) — real
│                                        body (was a placeholder since Phase 1); the only
│                                        caller of any plugin's Publishable.publish()
├── models/content.py                   + ContentPublishAttempt (content_item_id,
│                                        attempt_number, success, published_url, error,
│                                        created_at)
├── repositories/content_repository.py  + ContentPublishAttemptRepository
│                                        (list_by_content_item, next_attempt_number)
├── api/v1/content_items.py             + POST .../approve enqueues the job;
│                                        + POST .../retry-publish (manual re-enqueue);
│                                        + GET .../publish-attempts (the history)
├── schemas/content.py                   + PublishAttemptResponse
└── migrations/versions/
    9dccb14c2c88_add_content_publish_attempts.py   creates content_publish_attempts + its index
```

### How a publish attempt flows, end to end

1. `ContentApprovalService.approve()` (companion report) transitions the item to `approved`.
   `app/api/v1/content_items.py`'s `approve_content_item` route then calls
   `arq_redis.enqueue_job("publish_content_item", str(item.id), _job_id=f"publish-{item.id}")`
   — the **only** trigger for a publish attempt; nothing else in the codebase ever enqueues
   this job.
2. Arq's **publish queue** — a separate queue from agent-runs and event dispatch, per
   `docs/jobs/BACKGROUND_JOBS.md`'s per-category queue design — picks up the job and runs
   `publish_content_item(ctx, content_item_id)`.
3. The job loads the `ContentItem`. Two race-safety no-ops, both logged, neither an error:
   missing item (nothing to do), or `status != approved` (something else already moved it on
   — e.g. a previous attempt in the same Arq retry sequence already succeeded).
4. It computes `attempt_number` via `ContentPublishAttemptRepository.next_attempt_number` —
   `len(existing attempts) + 1`, so retries are numbered sequentially, not just re-recorded.
5. If `item.target_platform` is `None` (structurally un-retriable — no plugin was ever named),
   it records a failed attempt, sets `publish_error`, commits, and returns **without raising**
   — retrying the identical job would hit the exact same missing data every time, so there's no
   value in Arq's retry policy touching it.
6. Otherwise: `PluginRegistry(catalog, connections, settings).get(item.target_platform,
   Publishable)` resolves the project's plugin connection for that platform, structurally
   guaranteed to implement `Publishable` (raises `CapabilityNotSupported` otherwise — the same
   fail-fast single-plugin lookup pattern used elsewhere in the codebase, as opposed to the
   fan-out `all_with_capability` lookup Conversation Finder uses for `Searchable`).
7. `await plugin.publish(item)` — for Reddit (`plugins/reddit/plugin.py`), this posts
   `item.body` as a comment reply to `item.target_ref` (the Reddit `thing_id` Content Agent
   captured at draft time) via the plugin's own OAuth2-authenticated client, and returns a
   `PublishResult(success, published_url, error)`. No publish-specific code exists anywhere
   outside `plugins/reddit/plugin.py` and this one job — the job is generic across any
   `Publishable` plugin, by construction.
8. The attempt (success or failure) is recorded as its own `content_publish_attempts` row —
   unconditionally, regardless of outcome.
9. **On success:** `status → published`, `published_at` set, `publish_error` cleared, a
   `content_item.published` domain event is published (same transactional-outbox mechanism as
   `knowledge_item.created`), an `AuditLog(action="content_item.published", actor_user_id=None)`
   row is written, and the transaction commits.
10. **On failure:** `publish_error` is set, an
    `AuditLog(action="content_item.publish_failed")` row is written, the transaction commits
    (the attempt row and the audit row are durably recorded even though the overall job will
    be retried), and then `PublishAttemptFailed` is raised — purely to trigger Arq's own
    retry/backoff policy (`WorkerSettings.max_tries = 3`). The item's `status` stays `approved`
    throughout — a failed publish is never treated as, or silently converted into, a rejection.
11. After all automatic retries are exhausted, the item is left `approved` with
    `publish_error` populated, visible via `GET .../content-items/{id}` and
    `GET .../content-items/{id}/publish-attempts`. A human can trigger exactly one more attempt
    with `POST .../content-items/{id}/retry-publish`, which re-enqueues the identical
    idempotency-keyed job and writes its own `content_item.publish_retried` audit row
    (actor = the requesting user, unlike every other audit row this job writes, which are all
    system-initiated with `actor_user_id=None`).

### Design choices worth calling out

**Publish history is a dedicated table, not an extension of the single `publish_error`
column.** `content_items.publish_error` only ever holds the *most recent* failure — it cannot
answer "how many times has this been attempted, and what happened each time," which is what
"publish history" (an explicit Phase 2C requirement) actually means. `content_publish_attempts`
is append-only and keyed by `(content_item_id, attempt_number)`, recording every attempt
regardless of whether it was triggered by the initial approval, an automatic Arq retry, or a
manual `retry-publish` call.

**A failed attempt is recorded and committed *before* the job re-raises to trigger Arq's
retry.** If the attempt row were written only after a successful `session.commit()` at the very
end of the function, a crash between "plugin call failed" and "attempt recorded" would lose
the record of that attempt entirely. Committing the failure record first, then raising, means
the durable history is correct even if the process crashes immediately after — Arq's retry
would simply produce attempt N+1 next time, not silently reuse N.

**No application-layer validation (yet) requires `target_platform` to be set before an item can
be approved.** This is a real, acknowledged gap (not an oversight papered over): today nothing
stops `ContentApprovalService.approve()` from approving an item with `target_platform=None` —
it would be recorded as a permanently-failing publish attempt (step 5 above) rather than
rejected at approval time. Content Agent always sets `target_platform="reddit"` for every draft
it creates, so this can't happen via the one real code path that exists today, but it's called
out explicitly here as remaining work (§5) rather than silently assumed away.

**The publish job is idempotency-keyed by `content_item.id`, honoring a pre-existing (Phase
1-era) promise.** `app/jobs/publish.py`'s docstring has said "idempotency-keyed" since it was
still a placeholder; `_job_id = f"publish-{content_item_id}"` (verified against Arq's actual
`enqueue_job` signature via `inspect.signature`) makes a duplicate enqueue — a retried
`approve` API call, or `retry-publish` called before a still-queued attempt has run — a no-op
rather than a second concurrent publish attempt for the same item.

**Reddit-plugin-specific logic lives entirely inside `plugins/reddit/plugin.py`, never in
`app/jobs/publish.py`.** The job only knows about the generic `Publishable` Protocol
(`publish(item) -> PublishResult`); it has no `if platform == "reddit"` branch anywhere. This
mirrors the same "no plugin-specific logic outside the plugin" rule Content Agent's own
Reddit-awareness was checked against in the Phase 2B report — the *agent* is allowed to know
Reddit's `thing_id` convention because it's producing a `target_ref` for Reddit specifically;
the *publish worker* stays entirely platform-agnostic, because its job is "call whatever
`Publishable` plugin this project connected," not "know how Reddit posts comments."

---

## 2. Architecture compliance summary

| Requirement | Compliance |
|---|---|
| Publish Worker that consumes approved content | **Yes.** `publish_content_item` is the only code that transitions `approved → published`; its only trigger is an `approve` call (or a manual retry) — never a schedule, never automatic on any other condition. |
| Publishing through the Reddit plugin | **Yes, via the generic `Publishable` Protocol, not a Reddit-specific call.** `PluginRegistry.get(item.target_platform, Publishable)` resolves whichever plugin the project connected; today that's always Reddit, but the job itself has no Reddit-specific code. |
| Publish history | **Yes.** `content_publish_attempts`, one row per attempt, exposed via `GET .../publish-attempts`. |
| Error handling and retry support | **Yes.** Every attempt is recorded regardless of outcome; failures raise to trigger Arq's `max_tries=3` policy; after exhaustion, the item stays `approved`+`publish_error`-populated with a manual `retry-publish` endpoint, never silently dropped and never auto-transitioned to any other status. |
| Audit logging for every state transition | **Yes.** `content_item.published`, `content_item.publish_failed` (system-initiated, `actor_user_id=None`), and `content_item.publish_retried` (human-initiated, actor = the requesting user) — each written in the same transaction as the state/attempt change it describes. |
| Background event processing | **Yes.** A `content_item.published` domain event is published in the same transaction as the `status="published"` write, through the existing `EventPublisher`/transactional-outbox mechanism (`ARCHITECTURE.md` §7) — no new event mechanism was built; this is the outbox's third real event type after `knowledge_item.created` (Phase 2A) and the (unused-so-far) event categories from Phase 1. |
| Use the existing Conversation Finder / Knowledge Base / Content Agent / OAuth framework / Plugin SDK | **Yes.** The publish worker reads `item.target_platform`/`item.target_ref` (populated by Content Agent, Phase 2B) and resolves the project's plugin connection through the unmodified `PluginRegistry`/OAuth2 credential-decryption path (Phase 1/OAuth framework) — no new connection or credential mechanism was added for publishing. |
| Preserve every ADR and architectural decision | **Yes.** No ADR was touched. The publish worker's shape (a dedicated Arq job/queue, triggered only by approval) matches what `docs/jobs/BACKGROUND_JOBS.md` and `docs/api/API_DESIGN.md` already documented before this phase existed. |
| Preserve tenant isolation | **Yes.** The job loads the item by id (already project-scoped by the approve call that enqueued it) and resolves plugin connections via `PluginConnectionRepository.list_by_project(item.project_id)` — never a cross-project plugin lookup. |
| Preserve the event-driven architecture | **Yes.** `content_item.published` flows through the same outbox + dispatcher any future subscriber (e.g. a future Analytics Agent) would use, rather than a bespoke notification path built just for this. |
| Maintain strict typing, comprehensive testing, documentation standards | **Yes** — see §3. |
| Do NOT implement automatic publishing without approval / scheduling / other plugins/UI | **Yes, confirmed by absence.** The job's only entry points are `approve` and `retry-publish`, both human/API-triggered; no cron, no LinkedIn/X/Slack/email code, no frontend. |
| Every draft requires explicit human approval before publication | **Yes, architecturally.** `publish_content_item` itself re-checks `item.status == approved` before ever calling a plugin (step 3 above) — even a maliciously/accidentally enqueued job with an arbitrary `content_item_id` cannot publish anything not already in the `approved` state a human put it in. |

No frozen architectural decision, ADR, or locked decision was touched, reinterpreted, or
worked around.

---

## 3. Test results

**Full suite: 269 backend tests + 106 agents/plugins tests = 375 total, all passing** (see the
companion report for the approval-side portion of this total).

Tests specific to this report's scope:

- `backend/tests/integration/test_publish_worker.py` (**7 passed**, new file) — a successful
  publish transitions to `published`, records a successful attempt, publishes the
  `content_item.published` event, and writes the `published` audit row; a failed publish
  leaves the item `approved` with `publish_error` set, records a failed attempt, writes the
  `publish_failed` audit row, and raises `PublishAttemptFailed`; a second attempt after a first
  failure increments `attempt_number` (1, then 2); the job is a no-op (never calls the plugin)
  when the item isn't `approved`; the job is a no-op for a missing `content_item_id`; the job
  fails clearly (recorded attempt + `publish_error`, no raise) when `target_platform` is
  `None`; the job fails (via `CapabilityNotSupported`) when the project has no plugin
  connection for the target platform.
  - Uses a lightweight fixture `Publishable` plugin registered directly into
    `sys.modules[f"plugins.{key}.plugin"]` — the same technique the pre-existing
    `test_plugin_registry_credential_resolution.py` uses for its own fake plugin — so these
    tests exercise the real `PluginRegistry.get(..., Publishable)` resolution path without
    needing real Reddit OAuth credentials or network access.
- `backend/tests/integration/test_content_items_api.py` — the retry-publish/publish-attempts
  portion of its 15 total tests (9 new overall, split with the companion report): retry-publish
  requires the item to be `approved` (409 otherwise); retry-publish enqueues the job (asserted
  against the fake Arq client) and writes the `publish_retried` audit row; publish-attempts
  returns an empty list for an item with no attempts yet; publish-attempts 404s for an unknown
  item id.
- `backend/tests/integration/test_migrations.py` — `content_publish_attempts` added to
  `EXPECTED_TABLES`, confirming the migration creates exactly the table this report describes.

**Lint/type-check:** `ruff check` clean; `mypy --strict` clean, including
`# type: ignore[attr-defined]` on `result.rowcount` in `content_approval.py` (a real attribute
on the runtime `CursorResult` an UPDATE statement's `execute()` returns, not covered by the
generic `Result` stub) and the `publish_job` pytest fixture's lazy-import pattern needed
because `WorkerSettings.redis_settings` evaluates `get_settings()` at module-import time.

---

## 4. API documentation

| Method & path | Purpose |
|---|---|
| `POST /api/v1/projects/{project_id}/content-items/{id}/retry-publish` | 202. Manually re-enqueues the publish job for an `approved` item whose automatic retries are exhausted. 409 if the item isn't currently `approved`. Writes a `content_item.publish_retried` audit row (actor = the requesting user). |
| `GET /api/v1/projects/{project_id}/content-items/{id}/publish-attempts` | The full publish history for one item, ordered by `attempt_number`. 404 if the item doesn't exist or belongs to a different project. |

(`approve`, which is what actually triggers the *first* publish attempt, is documented in the
companion report — it belongs conceptually to the approval half of the workflow even though its
side effect is enqueuing this report's job.)

Example — checking why a publish keeps failing, then retrying manually:

```bash
curl http://localhost:8000/api/v1/projects/{project_id}/content-items/{item_id}/publish-attempts \
  --cookie "growthos_session=<cookie>"
# → [{"id": "...", "attempt_number": 1, "success": false, "published_url": null,
#     "error": "Rate limited — try again shortly.", "created_at": "..."},
#    {"id": "...", "attempt_number": 2, "success": false, "published_url": null,
#     "error": "Rate limited — try again shortly.", "created_at": "..."},
#    {"id": "...", "attempt_number": 3, "success": false, "published_url": null,
#     "error": "Rate limited — try again shortly.", "created_at": "..."}]

curl -X POST http://localhost:8000/api/v1/projects/{project_id}/content-items/{item_id}/retry-publish \
  --cookie "growthos_session=<cookie>"
# → 202 {"id": "...", "status": "approved", ...}   (unchanged until the job actually runs)
```

A successfully published item:

```bash
curl http://localhost:8000/api/v1/projects/{project_id}/content-items/{item_id} \
  --cookie "growthos_session=<cookie>"
# → {"id": "...", "status": "published", "published_at": "...", "publish_error": null, ...}
```

---

## 5. Remaining work before Phase 3 (Production Readiness)

- **No validation that `target_platform` is set before an item can be approved.** As noted in
  §1's design-choices section, this can't happen via Content Agent's real code path today, but
  nothing at the `ContentApprovalService`/API layer would stop it if a future agent (or a
  manual API call) approved an item with `target_platform=None` — it would fail every publish
  attempt permanently instead of being rejected up front, at approval time, where the mistake
  would be immediately visible.
- **A real, connected Reddit account and a real Anthropic API key.** Nothing in this phase or
  the two before it has made a real network call outside tests — the entire discover → draft →
  approve → publish chain has never actually posted a real comment to real Reddit.
- **No observability on publish attempts specifically.** `ARCHITECTURE.md` §10's planned
  OpenTelemetry spans don't wrap plugin `publish()` calls yet; today the only visibility is
  structured logs and the `content_publish_attempts` table itself.
- **No dashboard/UI surfacing publish failures.** `publish_error`/`publish-attempts` are
  API-only; a human has to know to check them, rather than being notified.
- **Other plugins' `Publishable` implementations** (LinkedIn, X, Slack, Email) — out of scope
  here by explicit instruction; the publish worker itself needs no changes to support them,
  since it's already generic over any `Publishable` plugin.
- **Scheduling** — deliberately not built; the publish job's only trigger remains a human
  `approve` or `retry-publish` call, permanently, per this task's non-goals and
  `ROADMAP.md`'s permanent "no autonomous publishing" constraint.
- See the companion report for what's left on the approval side specifically.
