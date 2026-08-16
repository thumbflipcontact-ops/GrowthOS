# n8n-nodes-threadly

An n8n community node for [Threadly](https://www.usethreadly.co) — an AI social-listening and
reply-drafting tool for X/Twitter. Every reply Threadly drafts sits in an Approval Inbox until
a human reviews it; nothing is ever posted automatically. This node lets an n8n workflow react
to what Threadly finds and participate in that review step.

## Installation

Follow the n8n [community nodes installation guide](https://docs.n8n.io/integrations/community-nodes/installation/),
using `n8n-nodes-threadly` as the package name.

## Credentials

You'll need a Threadly **API key**, generated from your project's Settings → API Keys page
(currently API-only — create one with):

```bash
curl -X POST https://<your-threadly-deployment>/api/v1/projects/{project_id}/api-keys \
  -H "Content-Type: application/json" \
  --cookie "growthos_session=<your dashboard session cookie>" \
  -d '{"name": "n8n"}'
```

The response's `full_key` is shown once — that's what goes into the node's credential.

## Resources & operations

- **Conversation** → List — X conversations Threadly has discovered for your project
- **Draft** → List / Approve / Reject — replies Threadly has drafted, awaiting your decision
- **Reply** → List — replies that have already been posted

## Trigger

**Threadly Trigger** fires whenever Threadly discovers a new conversation
(`conversation.discovered`). Activating the workflow registers a webhook subscription with
Threadly automatically; deactivating it tears the subscription back down. No polling.

## Compatibility

Tested against n8n's declarative node API v1. Requires a Threadly deployment running the
public API — see [docs/api/PUBLIC_API.md](https://github.com/thumbflipcontact-ops/GrowthOS/blob/main/docs/api/PUBLIC_API.md)
in the main GrowthOS repository for the full endpoint reference.

## License

[MIT](LICENSE.md)
