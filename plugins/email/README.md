# Plugin: Email

**Capabilities:** `Searchable`, `Publishable`, `WebhookReceivable`

## Purpose

Sends approved outreach/follow-up emails and detects inbound replies — the channel
`outreach_assistant` and `content_agent` rely on most for direct, one-to-one contact
follow-up.

## Auth

SMTP credentials or a transactional email provider API key (e.g. via a provider like
Postmark/SES — choose at implementation time based on deliverability needs), stored
encrypted. Inbound reply detection needs either IMAP polling or an inbound-parse webhook
from the provider.

## `publish()`

Sends an email per `ContentItem` (`type = email`), using `target_ref` as the recipient
contact's stored email address.

## `handle_webhook()`

Processes inbound-parse webhooks (provider-dependent) to detect replies, which updates the
relevant `contacts.status` to `replied` and can create a `knowledge_items` row if the reply
itself contains signal worth capturing (e.g. an objection, a feature request).

## Known constraints

Deliverability (SPF/DKIM/DMARC setup) is an operational concern outside this plugin's code
but a hard prerequisite for it to be useful — document the sending domain configuration in
`docs/deployment/DEPLOYMENT.md` once set up, not here.
