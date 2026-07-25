# API Design

## Style

REST over JSON, versioned in the URL path (`/api/v1/...`). No GraphQL — the frontend's data
needs are shaped closely enough around the domain model (projects → agents/knowledge/content)
that REST resource design maps naturally, and GraphQL's flexibility isn't buying anything
for a single-consumer (our own frontend) API. Revisit only if a public/partner API becomes a
real requirement — see `docs/decisions/`.

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
/api/v1/projects/{project_id}/content-items/{id}/reject                   POST
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

## Pagination, filtering, sorting

Cursor-based pagination (`?cursor=...&limit=...`) on all list endpoints, not offset-based —
`knowledge_items` and `content_items` are expected to grow continuously and offset pagination
degrades and can skip/duplicate rows under concurrent writes. Filtering via query params
scoped to indexed/enum columns (`?status=pending_review`, `?buying_intent=high`,
`?tags=indexing`) — filters map directly to the indexes described in
`docs/database/SCHEMA.md`; a filter that would require a full table scan is not exposed
until there's an index to back it.

## Response shape

```json
{
  "data": { ... } | [ ... ],
  "meta": { "next_cursor": "...", "total_returned": 20 }
}
```

Errors follow a single shape across the API — see `docs/errors/ERROR_HANDLING.md` for the
error envelope and status code conventions; this document doesn't duplicate it.

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

- No public/partner API surface — this is the frontend's API, not a product in itself yet.
- No GraphQL, no gRPC.
- No bulk-approve endpoint for content items — approval is deliberately per-item and
  per-click; batch approval would weaken the human-review guarantee the whole system exists
  to provide, so this is a permanent constraint, not a v1 gap. See `ARCHITECTURE.md` §8.
