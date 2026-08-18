# Public API

A second, separate API surface from the one described in `docs/api/API_DESIGN.md` — that
document covers the frontend's own API (`/api/v1/...`, cookie-session authed, one consumer:
the Threadly dashboard). This one is for external tools, starting with the
[n8n community node](https://github.com/thumbflipcontact-ops/n8n-nodes-threadly)
(`n8n-nodes-threadly`) — a separate public repo (this one stays private, and npm provenance
requires a public source repo), which duplicates the relevant parts of this reference in its
own README. A [ClawHub skill for OpenClaw agents](https://github.com/thumbflipcontact-ops/threadly-clawhub-skill)
(`threadly`) is also available — likewise a separate public repo (ClawHub's publish provenance
has the same public-source-repo requirement npm's does), documenting the same reference in its
`SKILL.md`.

## Auth

Every route below requires `Authorization: Bearer <api_key>`. Keys are project-scoped (one
key acts on exactly one project) and generated from the dashboard API — no public-API UI
exists for this yet:

```
POST   /api/v1/projects/{project_id}/api-keys      { "name": "..." }  -> { full_key, ... } (shown once)
GET    /api/v1/projects/{project_id}/api-keys
POST   /api/v1/projects/{project_id}/api-keys/{id}/revoke
```

See `backend/app/api/deps.py`'s `require_api_key_project` for the actual verification logic,
and `backend/app/services/api_key.py` for issuance/revocation.

Rate limit: 120 requests burst, 2/second sustained, per key (in-process only — see
`backend/app/core/rate_limit.py`).

## Endpoints

All under `/public/v1`:

| Method | Path | Notes |
|---|---|---|
| GET | `/conversations` | X conversations Threadly has discovered. `tag`, `limit`, `offset` query params. |
| GET | `/drafts` | Content items awaiting/given a decision. `status` (default `pending_review`), `limit`, `offset`. |
| POST | `/drafts/{id}/approve` | Approves a draft. Attributed to the API key's creator (`created_by_user_id`) — a key whose creator's account was deleted is rejected with 401. |
| POST | `/drafts/{id}/reject` | Body: `{"reason": "..."}`. Same attribution as approve. |
| GET | `/replies` | Content items already published. `limit`, `offset`. |
| POST | `/webhook-subscriptions` | Body: `{"target_url": "https://...", "event_types": ["conversation.discovered"]}`. `target_url` must be `https://` and not point at localhost/a private IP. Returns a `secret` shown once, used to verify delivery signatures. |
| GET | `/webhook-subscriptions` | Lists this project's subscriptions (never includes `secret`). |
| DELETE | `/webhook-subscriptions/{id}` | Revokes a subscription. |

## Webhook delivery

`conversation.discovered` fires whenever `conversation_finder` discovers a new lead (internally,
the domain event `knowledge_item.created` — translated to this external name at delivery time,
see `backend/app/core/webhooks/dispatcher.py`).

Delivered as `POST` to your `target_url`:

```json
{
  "event": "conversation.discovered",
  "delivery_id": "<uuid>",
  "occurred_at": "2026-08-16T10:00:00Z",
  "data": { "knowledge_item_id": "...", "url": "...", "platform": "twitter", "buying_intent": "high" }
}
```

Headers:

- `X-Threadly-Event: conversation.discovered`
- `X-Threadly-Delivery: <delivery id>` — stable per delivery attempt, safe to use as an
  idempotency key
- `X-Threadly-Signature: sha256=<hex>` — HMAC-SHA256 of the raw request body, keyed by the
  subscription's `secret`. Verify with `hmac.new(secret, raw_body, sha256).hexdigest()` and a
  constant-time comparison (see `backend/app/core/webhooks/signing.py` for the exact scheme).

Retries on failure with backoff (30s, 2m, 10m, 1h, 6h), terminal `failed` status after 5
attempts. No retry-triggered duplicate deliveries — one row per (subscription, event) pair.

## What's out of scope for now

- Additional webhook events beyond `conversation.discovered` (e.g. `draft.approved`,
  `draft.rejected`) — the domain events exist internally for some of these but aren't wired to
  the webhook dispatcher yet.
- Zapier/Make integrations — same underlying API, not yet built.
- Any dashboard UI for managing API keys or webhook subscriptions — API-only for now.
