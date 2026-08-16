# API Design

## Style

REST over JSON, versioned in the URL path (`/api/v1/...`). No GraphQL — the frontend's data
needs are shaped closely enough around the domain model (projects → agents/knowledge/content)
that REST resource design maps naturally, and GraphQL's flexibility isn't buying anything
for a single-consumer (our own frontend) API. A public/partner API did become a real
requirement (see "Public API" below) — it kept the same REST-over-JSON style rather than
introducing a second API paradigm, since nothing about the public API's needs argued for
GraphQL either.

## Public API

A second, separate router (`/public/v1/...`, `backend/app/api/public/v1/`) exists alongside
the one described in the rest of this document, for external tools — starting with an n8n
community node — to call. It is API-key-authed (`Authorization: Bearer <key>`, not the
cookie session every other route in this doc uses) and deliberately narrower: five endpoints
(list conversations/drafts/replies, approve/reject a draft) plus one webhook event,
`conversation.discovered`. See `docs/api/PUBLIC_API.md` for the full reference — everything
else in this document describes the frontend's own API only.

## Resource hierarchy

Every resource below `projects/{project_id}` is implicitly project-scoped — there is no
cross-project query endpoint. This mirrors the database scoping described in
`docs/database/SCHEMA.md` and is a deliberate constraint: an API shape that made
cross-project queries easy would invite exactly the kind of implicit tenant-boundary
crossing the schema design goes out of its way to avoid.

```
/api/v1/orgs/{org_id}
/api/v1/orgs/{org_id}/projects
/api/v1/plugins/catalog                                                    GET — every installed plugin's
                                                                             manifest (capabilities, content
                                                                             types, config_schema); drives the
                                                                             frontend's generic connection form,
                                                                             see docs/plugins/PLUGIN_ARCHITECTURE.md
/api/v1/projects/{project_id}
/api/v1/projects/{project_id}/plugin-connections                           GET — list; POST body validated
                                                                             against the target plugin's
                                                                             config_schema (rejects unknown
                                                                             plugin_key, undeclared
                                                                             capabilities, or a duplicate
                                                                             connection for the project).
                                                                             Credentials are wired separately,
                                                                             per auth_type — not part of this
                                                                             request body (see
                                                                             docs/auth/AUTHENTICATION.md).
                                                                             Writes an audit_log row — see
                                                                             app/services/plugin_connection.py.
/api/v1/projects/{project_id}/plugin-connections/{plugin_key}/oauth/start  POST — returns
                                                                             {authorize_url} for the frontend
                                                                             to navigate the browser to; also
                                                                             how reconnecting an expired/error
                                                                             connection is initiated. Body:
                                                                             {label?} (default "default"). See
                                                                             docs/auth/OAUTH2_ARCHITECTURE.md.
/api/v1/projects/{project_id}/plugin-connections/{connection_id}/oauth/disconnect
                                                                             POST — 204. Best-effort revokes at
                                                                             the provider, always clears local
                                                                             credentials regardless.
/api/v1/oauth/{plugin_key}/callback                                        GET — NOT project-scoped (a
                                                                             provider's registered redirect_uri
                                                                             must be one fixed URL; identity
                                                                             travels in the signed `state`
                                                                             param instead). Hit by a top-level
                                                                             browser redirect from the
                                                                             provider, not a frontend fetch() —
                                                                             always responds 302 to
                                                                             Settings.oauth_frontend_redirect_url
                                                                             with a query param indicating
                                                                             success/failure, never a raw JSON
                                                                             error body. See
                                                                             docs/auth/OAUTH2_ARCHITECTURE.md.
/api/v1/projects/{project_id}/agent-configs
/api/v1/projects/{project_id}/agent-configs/{agent_key}/runs
/api/v1/projects/{project_id}/agent-configs/{agent_key}/runs/trigger      POST — on-demand run
/api/v1/projects/{project_id}/knowledge-items
/api/v1/projects/{project_id}/knowledge-items/{id}
/api/v1/projects/{project_id}/content-items
/api/v1/projects/{project_id}/content-items/{id}
/api/v1/projects/{project_id}/content-items/{id}/approve                  POST
/api/v1/projects/{project_id}/content-items/{id}/reject                   POST { "version": 1, "reason": "..." }
/api/v1/projects/{project_id}/content-items/{id}/archive                  POST — not in the
                                                                             original design;
                                                                             added in Phase 2C,
                                                                             see ARCHITECTURE.md
                                                                             §8's implementation
                                                                             note. { "version": 1,
                                                                             "reason": "..."? }
/api/v1/projects/{project_id}/content-items/{id}/retry-publish            POST — manually
                                                                             re-enqueues the
                                                                             publish job for an
                                                                             `approved` item whose
                                                                             automatic retries are
                                                                             exhausted
/api/v1/projects/{project_id}/content-items/{id}/publish-attempts         GET — the publish
                                                                             history table, see
                                                                             docs/database/SCHEMA.md's
                                                                             content_publish_attempts
/api/v1/projects/{project_id}/companies
/api/v1/projects/{project_id}/contacts
/api/v1/projects/{project_id}/competitors
/api/v1/projects/{project_id}/competitors/{id}/observations
/api/v1/projects/{project_id}/daily-briefs
/api/v1/projects/{project_id}/daily-briefs/{date}
/webhooks/{plugin_key}                                                    POST — plugin ingress, see docs/plugins/PLUGIN_ARCHITECTURE.md
```

## The approval endpoints are the API's most important contract

```
POST /api/v1/projects/{project_id}/content-items/{id}/approve
POST /api/v1/projects/{project_id}/content-items/{id}/reject   { "reason": "..." }
```

These are the only two endpoints in the entire API that can move a `content_item` out of
`pending_review`. Both:
- Require an authenticated user (never a service/API-key principal — see
  `docs/auth/AUTHENTICATION.md`).
- Are the only call site in the codebase, along with `ContentApprovalService`, permitted to
  set `reviewed_by_user_id`/`reviewed_at`.
- Accept the `content_items.version` the client last read and pass it through to
  `ContentApprovalService`'s `where version = :expected` update. Return `409 Conflict` if the
  item is not currently `pending_review` **or** if `version` doesn't match — the latter is
  the concurrency guard from `ARCHITECTURE.md` §8: two racing approve/reject requests can
  never both succeed, the second always sees a version mismatch, not a silent double-write.
  No silent no-ops on a stale state — the client should refetch and show the user what
  actually happened.

No endpoint exists to directly set `content_items.status = 'published'` — that transition
only happens inside the publish worker, which isn't reachable via the public API at all.

**Implemented in Phase 2C** exactly as specified above — see
`docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md`. `archive` (not in this section's
original two-endpoint framing) follows the identical contract: version-guarded, 409 on a
state/version mismatch, writes `reviewed_by_user_id`/`reviewed_at` — the field names mean "a
human reviewed this," not specifically "approved," so archiving (also a human review
decision) uses them too.

## Pagination, filtering, sorting

Cursor-based pagination (`?cursor=...&limit=...`) on all list endpoints, not offset-based —
`knowledge_items` and `content_items` are expected to grow continuously and offset pagination
degrades and can skip/duplicate rows under concurrent writes. Filtering via query params
scoped to indexed/enum columns (`?status=pending_review`, `?buying_intent=high`,
`?tags=indexing`) — filters map directly to the indexes described in
`docs/database/SCHEMA.md`; a filter that would require a full table scan is not exposed
until there's an index to back it.

**Not yet true of any shipped endpoint, including Phase 2A's.** Every list endpoint built so
far (`projects`, `plugin-connections`, and Phase 2A's `agent-configs`/`.../runs`/
`knowledge-items`) uses plain `limit`/`offset` query params and returns a bare JSON array,
matching `app/repositories/base.py`'s `Repository.list_all(limit, offset)` convention rather
than this section's cursor design. Adopting cursor pagination is a cross-cutting change
better done once, consistently, across every list endpoint — not introduced piecemeal by
whichever endpoint happens to be built next. Tracked here rather than silently diverging from
this document.

## Response shape

```json
{
  "data": { ... } | [ ... ],
  "meta": { "next_cursor": "...", "total_returned": 20 }
}
```

**Also not yet true of any shipped endpoint** — every response so far is the bare
`data`-equivalent value directly (`response_model=list[X]` / `response_model=X`), no
envelope, no `meta`. Same reasoning as pagination above: a fleet-wide change, not a
per-endpoint one.

Errors follow a single shape across the API — see `docs/errors/ERROR_HANDLING.md` for the
error envelope and status code conventions; this document doesn't duplicate it. Error
responses *do* already match this document, unlike the two success-path conventions above.

## Idempotency

`POST` endpoints that trigger side effects with real-world consequences (`.../runs/trigger`,
`.../approve`) accept an optional `Idempotency-Key` header, honored for 24 hours — prevents
a double-click or a retried request from triggering two agent runs or (worse) double-firing
an approval side effect.

## Webhook ingress

`/webhooks/{plugin_key}` is unauthenticated at the HTTP layer (external systems can't present
GrowthOS session credentials) but each plugin's `handle_webhook()` implementation verifies
the payload's authenticity per that provider's mechanism (signature header, shared secret,
etc.) before processing — see the specific plugin's `README.md`. A webhook that fails
verification is logged and dropped, never processed. A verified webhook writes its resulting
row and domain event in one transaction, exactly like a scheduled agent run — see
`ARCHITECTURE.md` §7.

## What's intentionally not in v1

- No org-scoped (multi-project) API keys for the public API — see `docs/api/PUBLIC_API.md`.
  Every key is scoped to one project, matching this doc's own project-scoping convention.
- No GraphQL, no gRPC.
- No bulk-approve endpoint for content items — approval is deliberately per-item and
  per-click; batch approval would weaken the human-review guarantee the whole system exists
  to provide, so this is a permanent constraint, not a v1 gap. See `ARCHITECTURE.md` §8.
