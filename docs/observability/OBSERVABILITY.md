# Observability

**New in Version 2.** The original design had a thorough logging strategy
(`docs/logging/LOGGING.md`) but no metrics or tracing story at all — flagged 🟠 in the
Principal Engineer design review (`docs/reviews/DESIGN_REVIEW.md` §7.1) specifically because
of GrowthOS's 100+ plugin requirement: the dominant operational question in that world is
"which of my N connected plugins is degraded right now," and logs — even good structured
ones — answer an aggregate question like that badly. This document is the real workstream
that closes that gap, not a documentation-only addition; see
`docs/architecture/LOCKED_DECISIONS.md` §2 for its implementation timing.

## What gets instrumented

**Every plugin capability call** (`search()`, `publish()`, `handle_webhook()`,
`query_metrics()`) gets an OpenTelemetry span, tagged `plugin_key`, `project_id`, and the
capability name. **Every agent run** gets a span, tagged `agent_key`, `project_id`, and
whether it was schedule- or event-triggered. **Event dispatch** gets a span per
(event, subscriber) pair, tagged `event_type`, `subscriber_key`.

## Why this matters specifically because of the 100+ plugin requirement

With 3–12 plugins, "is Reddit working right now" is answerable by glancing at recent logs.
With 100+, plugins fail independently and continuously at the margins (one hits a rate limit,
another's OAuth token expires, a third's upstream API has a partial outage) — and the
question stops being "is X working" and becomes "which of my plugins need attention right
now, ranked by how much they need it." That's an aggregation query, not a log grep. Metrics
exist to make that query cheap.

## Metrics and dashboards

Exported to Prometheus (self-hosted alongside the existing Docker Compose stack — see
`docs/deployment/DEPLOYMENT.md`; a hosted alternative like Grafana Cloud's free tier is an
equally valid substitute, left flexible per `docs/architecture/LOCKED_DECISIONS.md` §2),
with Grafana dashboards for:

- **Per-plugin health:** success rate and p50/p95 latency for every capability call, broken
  out by `plugin_key` — the primary "which plugin needs attention" view.
- **Per-agent health:** run duration, outcome distribution (succeeded / failed / partial
  failure — see `docs/errors/ERROR_HANDLING.md`'s fail-soft-per-source policy), broken out by
  `agent_key`.
- **Event dispatch lag:** age of the oldest undispatched `domain_events` row, per project.
  This is *the* health signal for the entire event architecture (`ARCHITECTURE.md` §7) — a
  growing lag means the dispatcher is falling behind or stuck, and webhook-triggered
  reactivity (the whole point of the event model) is silently degrading.
- **Rate-limit pressure:** how often each plugin's shared rate limiter
  (`docs/plugins/PLUGIN_ARCHITECTURE.md` §Rate limiting) is actually throttling calls — the
  leading indicator before a plugin's success rate visibly drops.

## Alerting (minimal, for v1)

Three alerts are worth having from day one, before the rest of the dashboard set is built
out: event dispatch lag exceeding a threshold (e.g. 5 minutes — the event architecture is
supposed to be near-real-time; a growing lag means it isn't), any plugin's success rate
dropping below a threshold sustained over a window (not a single blip), and any agent's run
failure rate doing the same. Everything else in this document is for investigation once
something's already been flagged; these three are for finding out something needs
investigating in the first place.

## Relationship to logging

Metrics and traces answer "what's happening in aggregate, right now." Logs
(`docs/logging/LOGGING.md`) answer "what exactly happened in this one specific run." They're
complementary, not redundant — a metrics dashboard tells you Reddit's success rate dropped at
2pm; the structured logs for that window tell you it was hitting a 429. Neither replaces the
other, and this document doesn't change anything in `docs/logging/LOGGING.md`.

## Scope note

This document covers system observability (is GrowthOS itself healthy). It is not about
product analytics (which content types perform best, which channels convert) — that's
`analytics_agent`'s eventual job (Phase 3, deferred — see `ROADMAP.md`), operating on
GrowthOS's own domain data (`content_items`, `knowledge_items` outcomes), not on
infrastructure metrics.
