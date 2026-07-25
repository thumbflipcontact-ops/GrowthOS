# Plugin: Slack

**Capabilities:** `Searchable`, `Publishable`, `WebhookReceivable`

## Purpose

Two distinct uses, both Phase 3: (1) internal notifications — GrowthOS posting the Daily
Brief or urgent flags (e.g. a high buying-intent thread) into the founder's own Slack; (2)
community monitoring — for founders whose ICP congregates in specific Slack communities the
project has access to.

## Auth

Slack app OAuth2 (bot token), scoped per use case — notification-only usage needs
`chat:write` alone; community monitoring additionally needs `channels:history` and is only
possible in workspaces the connected app has been invited to.

## `publish()`

Posts a message per `ContentItem` (internal notification) or a community reply, depending on
`target_platform` context stored on the item.

## `handle_webhook()`

Slack Events API push for real-time mention/message detection in monitored channels.

## Known constraints

Internal notifications (Daily Brief delivery) are a lower-stakes use of `publish()` than
external community replies — worth keeping as clearly separated code paths within this
plugin even though both go through the same `publish()` method, since only one of them is
external-facing content requiring the full `ContentItem` approval gate. The notification use
case should be modeled as a system message, not a `ContentItem`, precisely because it isn't
externally visible content — see `docs/api/API_DESIGN.md` for where that distinction is
drawn.
