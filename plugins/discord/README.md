# Plugin: Discord

**Capabilities:** `Searchable`, `Publishable`, `WebhookReceivable`

## Purpose

Community monitoring and engagement for ICPs that congregate in Discord servers (common for
developer-tool and indie-SaaS audiences) — analogous to the Slack plugin's community-side
use case, without the internal-notification use case.

## Auth

Discord bot token, stored encrypted, invited to the specific servers a project wants to
monitor. Requires `MESSAGE_CONTENT` intent for `search()`/`handle_webhook()` to read message
content, which requires the bot to be verified if the server count grows past Discord's
threshold — worth noting here since it's an operational, not code-level, blocker.

## `search()`

Reads recent messages from configured channels for relevant discussion.

## `publish()`

Posts an approved reply into a configured channel/thread.

## `handle_webhook()`

Real-time message events via Discord's Gateway (technically a persistent connection rather
than a classic webhook — this plugin's `WebhookReceivable` implementation is a
long-running gateway listener process rather than an HTTP ingress route; document this
distinction clearly at implementation time since it changes the deployment shape, see
`docs/deployment/DEPLOYMENT.md`.
