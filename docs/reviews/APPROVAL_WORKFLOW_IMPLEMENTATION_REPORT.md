# Approval Workflow Implementation Report (Phase 2C, part 1 of 2)

**Date:** 2026-07-26
**Scope:** the human-review half of Phase 2C — `ContentApprovalService`, the approve/reject/
archive workflow, state-transition validation, optimistic concurrency enforcement, the
approval API endpoints, and audit logging for every transition. The self-check/auto-advance
step (`draft → pending_review`) is documented here too, since it's what gives
`ContentApprovalService` anything to act on — see §1's architecture note. Publishing itself
(the `approved → published` transition and everything downstream of it) is covered in the
companion report, `docs/reviews/PUBLISHING_WORKFLOW_IMPLEMENTATION_REPORT.md`.

---

## 1. Approval Workflow Implementation Report

### What was built

```
backend/app/
├── services/
│   ├── content_self_check.py    run_self_check(body, max_length, banned_phrases) →
│   │                              SelfCheckResult(passed, reasons) — pure function, no I/O
│   ├── content_drafts.py         + ContentDraftClient.submit_for_review(item, ...) — runs
│   │                              the self-check and, if it passes, advances draft →
│   │                              pending_review and writes an audit row (create_draft
│   │                              itself is UNCHANGED, still only ever writes "draft")
│   └── content_approval.py       ContentApprovalService — approve/reject/archive, each a
│                                   thin wrapper over one shared _transition() method
├── api/v1/content_items.py       + POST .../approve, .../reject, .../archive
├── schemas/content.py             + ApproveContentItemRequest, RejectContentItemRequest,
│                                    ArchiveContentItemRequest
├── models/content.py              + ContentItemStatus.ARCHIVED, + ContentPublishAttempt
│                                    (used by the publish side, see the companion report)
└── migrations/versions/
    f10c53cf3185_add_archived_content_item_status.py   ALTER TYPE ... ADD VALUE 'archived'

agents/content_agent/
├── agent.py     + calls ctx.content.submit_for_review(...) right after create_draft
└── config.py    + banned_phrases: list[str]
```

### How a draft becomes reviewable, then decided, end to end

1. `ContentAgent.run()` (Phase 2B, unchanged) calls `ctx.content.create_draft(...)` exactly as
   before — the row is written with `status="draft"`, full stop. `create_draft` has no status
   parameter; this guarantee is unchanged from Phase 2B.
2. **New in Phase 2C:** immediately after, the agent calls
   `ctx.content.submit_for_review(saved, org_id=..., max_length=config.max_reply_length,
   banned_phrases=config.banned_phrases)`. This runs `run_self_check()` — a length check and a
   case-insensitive banned-phrase check — against the draft's `body`.
   - If it **passes**: the item's `status` is set to `pending_review`, flushed, and an
     `AuditLog(action="content_item.submitted_for_review", actor_user_id=None)` row is written
     (actor is `None` — this is an automatic transition, not a human decision).
   - If it **fails**: nothing changes. The item stays `draft` forever, with no audit row and no
     path back into the review queue — the agent's `AgentResult.summary` records
     `self_check_passed=False` and the specific `reasons`, but this is intentionally a dead
     end today (see §5 "remaining work" for what closes it later).
3. A human lists `pending_review` items via `GET .../content-items?status=pending_review`
   (Phase 2B's existing read API, unchanged), reads `body`/`confidence`/`reasoning`/`evidence`,
   and decides.
4. **Approve:** `POST .../content-items/{id}/approve {"version": N}` →
   `ContentApprovalService.approve()` → one atomic `UPDATE` moves `pending_review → approved`,
   sets `reviewed_by_user_id`/`reviewed_at`, bumps `version`, writes an
   `AuditLog(action="content_item.approved", actor_user_id=<the reviewer>)` — then the API
   layer enqueues the publish job (see the companion report; `ContentApprovalService` itself
   never touches a plugin).
5. **Reject:** `POST .../content-items/{id}/reject {"version": N, "reason": "..."}` → the same
   pattern, `pending_review → rejected`, `reason` stored in the audit row's `metadata_`
   (`{"reason": reason}`) — no new column added for it, since `reviewed_by_user_id`/
   `reviewed_at` already prove who and when.
6. **Archive:** `POST .../content-items/{id}/archive {"version": N, "reason": null}` — reachable
   from `draft` **or** `pending_review` (not from anything already decided or published),
   `reason` optional. This is the one addition beyond ARCHITECTURE.md §8's original 4-state
   diagram — see the architecture note below.
7. Every one of steps 4–6 is a single `UPDATE ... WHERE id = :id AND project_id = :project_id
   AND version = :expected AND status IN (:allowed_from_statuses)`. A concurrent second request
   racing the first (same version, different intended transition) always affects zero rows and
   gets `InvalidStateTransition` (409) — never a silent double-transition, never a torn write.

### Architecture note: the gap this phase found, and how it was resolved

Building `ContentApprovalService` strictly against ARCHITECTURE.md §8 (frozen, adversarially
reviewed) exposed a real conflict, not a hypothetical one: that section documents drafts as
"always created in draft, immediately auto-advanced to pending_review once the agent's own
self-check passes," and says approve/reject act **only** on `pending_review`. But Phase 2B's
Content Agent — per that phase's own explicit, deliberate instructions — left every draft in
`draft` forever, with no promotion mechanism at all. Built strictly, `ContentApprovalService`
would have had nothing to approve or reject; every Phase 2B draft would be permanently
unreachable by it. Separately, "Archive" (required by this phase) has no place in that
section's original 4-state diagram at all.

Per this phase's own instruction — "if implementation exposes an architectural limitation,
stop and ask before introducing a breaking change" — this was not guessed at. Two questions
were put to the user directly, with these answers:

1. **How to close the draft → pending_review gap:** build the missing auto-advance step now,
   matching ARCHITECTURE.md §8 exactly (rejected alternative: having
   `ContentApprovalService` accept `draft` as a fourth reviewable status directly, which would
   have quietly deviated from the documented state machine rather than completing it).
2. **How to add Archive:** a new, genuine `archived` enum value (rejected alternative:
   aliasing archive to the existing `rejected` status, which would have conflated "a human
   actively rejected this" with "this was archived/withdrawn without a rejection decision" —
   two different facts a future audit or metrics query would want to distinguish).

Both are implemented exactly as decided. Nothing about ARCHITECTURE.md §8's original 4-state
diagram was changed — `archived` and the self-check step are additive, documented in §8 as an
"Implemented" addendum rather than a revision to the original text.

### Design choices worth calling out

**`create_draft` and `submit_for_review` are deliberately two separate methods, not one.**
Folding the self-check into `create_draft` itself would have made "this method only ever
writes `draft`" no longer true — a guarantee Phase 2B relied on being exact. Keeping them
separate means each method's contract stays precise (`create_draft`: always `draft`;
`submit_for_review`: `draft → pending_review`, conditionally) while the agent's overall
observed behavior — "created in draft, immediately auto-advanced" — matches ARCHITECTURE.md
§8's wording when both are called back to back, which `ContentAgent.run()` now does.

**`reviewed_by_user_id`/`reviewed_at` mean "a human reviewed this," not specifically
"approved."** Archive is also a human decision, so it sets both fields too, identically to
approve/reject. Only `submit_for_review`'s automatic transition leaves them untouched — it
isn't a human review, and the database's `review_fields_consistent` check constraint (Phase 0,
unchanged) continues to hold: those two fields are set together or not at all, regardless of
which of the three human transitions triggered it.

**No new column for reject/archive reasons.** `audit_log.metadata_` (JSONB, pre-existing since
Phase 0) already exists specifically to carry per-action context; `{"reason": reason}` fits it
exactly. Adding a `content_items.rejection_reason` column would have duplicated a fact the
audit trail already records, for no query benefit `content_items.reviewed_at` scoped by
`audit_log` doesn't already provide.

**The concurrency guard is one atomic `UPDATE`, not `SELECT ... FOR UPDATE` then a second
`UPDATE`.** `docs/database/SCHEMA.md` and `docs/api/API_DESIGN.md` both already documented
`version = :expected` as the mechanism; `_transition()` folds the state-transition check and
the version check into the same `WHERE` clause of a single statement, so there is no window
between "check" and "write" for a second request to land in — the two checks and the write are
one indivisible operation, not sequential steps that could race each other.

**The reused, not reinvented, exception.** `InvalidStateTransition` (`app/core/errors.py`)
already existed since Phase 0 with a docstring covering both an illegal transition and a stale
`version` — no new exception class was needed; `_transition()`'s zero-rowcount branch is the
first code to actually raise it for real.

---

## 2. Architecture compliance summary

| Requirement | Compliance |
|---|---|
| `ContentApprovalService` | **Yes.** `approve`/`reject`/`archive`, each delegating to a shared, private `_transition()` — no duplicated transition logic across the three. |
| Approve / Reject / Archive workflow | **Yes.** All three implemented; archive is additive to ARCHITECTURE.md §8's original diagram, decided by explicit user direction (see §1's architecture note), not unilaterally. |
| State-transition validation | **Yes.** `_REVIEWABLE_STATUSES = (pending_review,)` for approve/reject; `_ARCHIVABLE_STATUSES = (draft, pending_review)` for archive — enforced in the same `UPDATE`'s `WHERE` clause, not a separate pre-check that could race the write. |
| Optimistic concurrency via the existing `version` field | **Yes.** `WHERE ... AND version = :expected`, `SET version = version + 1` — the exact mechanism `docs/database/SCHEMA.md` and `docs/api/API_DESIGN.md` documented since Phase 0, now actually implemented for the first time. |
| Approval API endpoints | **Yes.** `POST .../approve`, `.../reject` (`reason` required), `.../archive` (`reason` optional) — see §4. |
| Audit logging for every state transition | **Yes.** Every one of `submitted_for_review`/`approved`/`rejected`/`archived` writes its own `AuditLog` row, actor `None` for the automatic transition and the reviewing user's id for the three human ones. |
| Use the existing Conversation Finder / Knowledge Base / Content Agent / Reddit plugin / OAuth framework / Plugin SDK | **Yes, for this report's scope.** This half of the phase touches none of them directly — `ContentApprovalService` operates purely on `content_items`; the Content Agent change is the two-line addition of a `submit_for_review` call, nothing about its own drafting logic changed. See the companion report for how the publish side uses the Reddit plugin/Plugin SDK. |
| Preserve every ADR and architectural decision | **Yes.** ARCHITECTURE.md §8's original 4-state diagram is unchanged; `archived` and the self-check step are additive, documented as an "Implemented" addendum in §8, not a rewrite of the frozen text. No `docs/architecture/LOCKED_DECISIONS.md` entry was touched. |
| Preserve tenant isolation | **Yes.** Every `_transition()` call is scoped by both `item_id` and `project_id` in the same `WHERE` clause; `get_scoped()` (used for the initial existence check) 404s for a correct id belonging to a different project — tested explicitly (`test_approve_returns_404_for_an_item_in_a_different_project`). |
| Preserve the event-driven architecture | **Yes.** No new event type was needed for approve/reject/archive themselves — they're synchronous API-triggered transitions, exactly as `docs/api/API_DESIGN.md` always specified (the API layer enqueues the publish job directly from `approve`, not via a domain event; publishing already has its own dedicated job category per `docs/jobs/BACKGROUND_JOBS.md`). |
| Maintain strict typing, comprehensive testing, documentation standards | **Yes** — see §3. `mypy --strict` clean; `ruff check` clean. |
| Do NOT implement automatic publishing without approval / scheduling / other plugins/UI | **Yes, confirmed by absence.** `ContentApprovalService` never calls a plugin; nothing in this report's files references a schedule, LinkedIn/X/Slack/email, or any frontend code. |
| Every draft requires explicit human approval before publication | **Yes, architecturally.** No code path anywhere sets `status = "published"` except the publish worker (companion report), whose only trigger is the `approve` transition documented here (or a human-initiated manual retry). |

No frozen architectural decision, ADR, or locked decision was touched, reinterpreted, or
worked around without the explicit user sign-off documented in §1's architecture note.

---

## 3. Test results

**Full suite: 269 backend tests + 106 agents/plugins tests = 375 total, all passing** (see
the companion report for the publish-side portion of this total).

Tests specific to this report's scope:

- `backend/tests/unit/test_content_self_check.py` (**9 passed**) — clean body passes; empty
  or whitespace-only body fails; a body over `max_length` fails; a body exactly at
  `max_length` passes; a banned phrase fails case-insensitively; no banned phrases configured
  never fails that check; multiple simultaneous failures are all reported; blank/empty banned
  phrases in the list are ignored.
- `backend/tests/integration/test_content_drafts_client.py` (**5 passed**, 3 new) —
  `submit_for_review` advances a passing draft to `pending_review` and writes an audit row;
  leaves a failing draft in `draft` with no audit row; checks banned phrases in addition to
  length.
- `backend/tests/integration/test_content_approval_service.py` (**10 passed**, new file) —
  approve succeeds and writes an audit row; reject succeeds with a reason recorded in the
  audit row's metadata; archive succeeds from `draft`; archive succeeds from
  `pending_review`; approve rejects (409) a `draft` item; approve rejects (409) an
  already-`approved` item; archive rejects (409) a `published` item; approve rejects (409) a
  stale `version`; two concurrent approve/reject calls on the same item — only one wins, the
  other gets a 409, never both; 404 for an item id belonging to a different project; 404 for
  an unknown item id.
- `backend/tests/integration/test_content_items_api.py` (**15 passed**, 9 new) — approve
  transitions to `approved` and enqueues the publish job (asserted against a fake Arq client's
  captured job name/args/`_job_id`); approve rejects a `draft` item (409); approve rejects a
  stale version (409); reject requires a `reason` (422 without one, 200 with one); archive
  from `draft` without a reason succeeds. (The remaining 6 of these 15 are retry-publish/
  publish-attempts tests — see the companion report.)
- `agents/content_agent/tests/test_agent.py` (**13 passed**, 2 new) — a reply exceeding
  `max_reply_length` fails the self-check and stays in `draft`; a reply containing a banned
  phrase fails the self-check.
- `backend/tests/integration/test_run_agent_for_event_job.py` (**7 passed**, 1 new + 1 fixed)
  — the existing "drafts and persists a content item" test now asserts the final status is
  `pending_review` (was `draft` in Phase 2B, correctly updated now that auto-advance runs
  automatically as part of the same agent run); a new test configures `max_reply_length=50` and
  asserts a too-long reply stays in `draft` with `self_check_passed=False` recorded in the run
  summary.

**Lint/type-check:** `ruff check` clean; `mypy --strict` clean across all 84 files in
`backend/app/` and all 25 files across `agents/_shared`, `agents/conversation_finder`,
`agents/content_agent` (including every test file in all three).

---

## 4. API documentation

All three endpoints are project-scoped, depend on `require_project_access` and
`get_current_user` (never a service/API-key principal — only an authenticated human can
approve/reject/archive), and accept the item's currently-known `version`.

| Method & path | Body | Purpose |
|---|---|---|
| `POST /api/v1/projects/{project_id}/content-items/{id}/approve` | `{"version": 1}` | `pending_review → approved`. Enqueues the publish job. 409 if not currently `pending_review` or if `version` doesn't match. |
| `POST /api/v1/projects/{project_id}/content-items/{id}/reject` | `{"version": 1, "reason": "..."}` | `pending_review → rejected`. `reason` is required (422 without one). 409 on state/version mismatch. |
| `POST /api/v1/projects/{project_id}/content-items/{id}/archive` | `{"version": 1, "reason": "..."?}` | `draft` or `pending_review` → `archived`. `reason` optional. 409 on state/version mismatch. |

Example — approving a drafted reply after reading it:

```bash
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/content-items/{item_id}/approve \
  --cookie "growthos_session=<cookie>" \
  -H "Content-Type: application/json" \
  -d '{"version": 1}'
# → 200 {"id": "...", "status": "approved", "version": 2,
#        "reviewed_by_user_id": "...", "reviewed_at": "...", ...}
```

Rejecting instead, with a reason:

```bash
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/content-items/{item_id}/reject \
  --cookie "growthos_session=<cookie>" \
  -H "Content-Type: application/json" \
  -d '{"version": 1, "reason": "too generic, doesn'"'"'t address the actual question"}'
# → 200 {"id": "...", "status": "rejected", "version": 2, ...}
```

A stale or wrong-state request gets a 409, not a silent no-op:

```bash
curl -X POST .../approve --cookie "..." -d '{"version": 1}'
# → 409 {"error": {"code": "invalid_state_transition",
#         "message": "content_item ... cannot transition to 'approved': current status is
#                      'approved' (expected one of ['pending_review']), or its version has
#                      changed since you last read it (you supplied version=1, current
#                      version=2)."}}
```

---

## 5. Remaining work before Phase 3 (Production Readiness)

- **No path back into review for a self-check failure.** A draft that fails `submit_for_review`
  stays `draft` forever with no retry/edit mechanism — today this is a silent dead end, visible
  only via `AgentResult.summary`, not surfaced anywhere a human would see it without checking
  agent run logs directly.
- **No bulk approve/reject/archive.** Deliberately out of scope per `docs/api/API_DESIGN.md`'s
  permanent (not just v1) constraint — approval is per-item, per-click, to protect the
  human-review guarantee.
- **No frontend.** Every transition in this report has only been exercised via the API
  (`curl`/tests) — nothing renders a review queue for a human to actually click through.
- **Duplicate-content detection** — named in the original Content Agent spec's self-check
  description, explicitly not implemented (see `content_self_check.py`'s docstring); would
  need to query recent `content_items` for similarity, a materially bigger feature than the
  length/banned-phrase checks built here.
- **An `Idempotency-Key` header isn't honored yet** on `approve`, despite
  `docs/api/API_DESIGN.md` documenting it for side-effectful POSTs — today, a duplicate
  approve request for an already-`approved` item correctly 409s (not a silent double-publish,
  since the publish job itself is separately idempotency-keyed by `content_item.id`), but a
  literal duplicate *approve* click before the first request's response returns isn't
  deduplicated by header, only by the version guard naturally rejecting the second one once
  the first has committed.
- See the companion report for what's left on the publishing side specifically.
