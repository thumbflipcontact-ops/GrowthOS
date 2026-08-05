# Roadmap

This roadmap is organized by phase, not by date. Each phase has an explicit exit criterion —
we move on when the criterion is met, not when a calendar date arrives. Anything not listed
under a phase is deliberately out of scope for that phase; see §Deferred for what's excluded
and why.

## Phase 0 — Foundation (complete)

Design documentation, a Principal Engineer design review, and the resulting Version 2
architecture. No product code — see `ARCHITECTURE_FREEZE.md` at the repo root for the freeze
declaration.

**Exit criterion (met):** architecture reviewed adversarially
(`docs/reviews/DESIGN_REVIEW.md`), revised (`ARCHITECTURE.md`, now Version 2), locked
(`docs/architecture/LOCKED_DECISIONS.md`), and audited for internal consistency across the
repository. See `ARCHITECTURE_FREEZE.md`.

## Phase 1 — Single-project skeleton

Goal: prove the core loop end-to-end for one project (ScoutSEO), with one plugin and two
agents, on the V2 foundation — built once, in the order below, not built against V1 and
reworked. This ordering is what the (now-archived) V1→V2 migration plan produced; see
`docs/architecture/archive/MIGRATION_V1_TO_V2.md` for the full reasoning behind each step.

1. **Schema foundation** — `database/schema.sql` as it stands today (V2 shape: no
   `content_item_type` enum, `plugin_catalog`, `domain_events`, `plugin_connections.config`,
   `content_items.version`, `audit_log` all present from the start).
2. **Plugin core** — manifest/entry-point discovery, the four segmented capability Protocols,
   the `PluginCatalog` scanner, `plugin_connections.config` validation. Exit check: a trivial
   test plugin is discoverable and shows up via `GET /api/v1/plugins/catalog` before any
   Reddit-specific code exists.
3. **Event core** — `domain_events` outbox, `EventPublisher`, the Arq event-dispatch
   periodic job, `agents/_shared/subscriptions.py`. Exit check: a published test event
   reaches a subscribed test handler within one dispatch cycle, and survives a simulated
   dispatcher crash mid-cycle.
4. **Reddit plugin** — `plugins/reddit/`, against the mechanism built in step 2, not a
   hand-registered one-off. See `plugins/reddit/README.md` and
   `docs/decisions/0005-first-plugin-reddit.md`. **Done** — implemented against the platform
   mechanisms built in steps 2 and 6 (manifest/discovery, and the OAuth2 framework/envelope
   encryption respectively), including its own unit + contract test suite. Not yet connected
   to a real account — the one thing step 5's Conversation Finder, Content Agent, and
   approval/publish workflow still don't change; see
   `docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md`. **Extended with two more channel
   plugins** — `plugins/twitter/` (searchable + publishable, OAuth2 + PKCE — the case the
   OAuth2 framework's PKCE support was originally built for) and `plugins/linkedin/`
   (publishable only; LinkedIn's public API has no general content-search endpoint for a
   standard app, see `plugins/linkedin/README.md` §"Why no search()"), both against the same
   platform mechanisms with their own unit + contract test suites, neither yet connected to a
   real account; see `docs/reviews/TWITTER_LINKEDIN_IMPLEMENTATION_REPORT.md`.
5. **Conversation Finder + Content Agent** — Conversation Finder remains schedule-triggered
   (it originates discovery); Content Agent subscribes to `knowledge_item.created` instead of
   being placed in a sequencing config. **Done, in two sub-phases:**
   - **Phase 2A — Conversation Finder.** `agents/conversation_finder/`, built against the
     mechanisms from steps 2–4 (plugin capability discovery, the event outbox, the Reddit
     plugin) plus the first concrete `KnowledgeBaseClient` and real `run_scheduled_agent` job
     wiring. Rule-based ranking/scoring, not LLM-based — no LLM integration existed yet, so
     `knowledge_items.problem`/`industry`/`product`/`pain_point`/`buying_intent`/`suggested_*`
     stay unpopulated pending a future enrichment pass. See
     `docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md` and `CHANGELOG.md`'s
     `[0.4.0]` entry (tagged `v0.4.0-conversation-finder`).
   - **Phase 2B — Content Agent.** `agents/content_agent/`, the first agent triggered by the
     event bus's subscription path (`app/jobs/events.py`'s `run_agent_for_event`, wired for
     real alongside it) rather than the scheduler. Also the first consumer of a real
     `LLMProvider` (`backend/app/core/llm/`, Claude via `AnthropicProvider` — ADR 0004,
     finally implemented). Drafts Reddit replies only, created `draft` then auto-advanced to
     `pending_review` by its own self-check (see the Phase 2C sub-bullet below — built
     alongside it once ARCHITECTURE.md §8's documented flow required it). Required
     extending the Phase 2A schema (`knowledge_items.title`/`body_excerpt`/`platform_metadata`,
     `content_items.confidence`/`reasoning`/`evidence`) once a real consumer needed
     grounding text and self-assessment fields nothing had persisted before. See
     `docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md` and `CHANGELOG.md`'s `[0.5.0]`
     entry (tagged `v0.5.0-content-agent`).
   - **Phase 2C — Approval + publish worker.** `ContentApprovalService`
     (`approve`/`reject`/`archive`, atomic version-guarded transitions per ARCHITECTURE.md
     §8), the self-check/auto-advance step (`ContentDraftClient.submit_for_review`, built
     here rather than in Phase 2B once ARCHITECTURE.md §8's documented flow proved it was
     needed for approve/reject to have anything to act on), the real publish worker
     (`app/jobs/publish.py`, the only caller of any plugin's `Publishable.publish()`), and a
     new `archived` status (a fifth terminal state beyond the original diagram — see
     ARCHITECTURE.md §8's implementation note). See
     `docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md`,
     `docs/reviews/PUBLISHING_WORKFLOW_IMPLEMENTATION_REPORT.md`, and `CHANGELOG.md`'s
     `[0.6.0]` entry (tagged `v0.6.0-approval-publishing`).
6. **Credential encryption** — envelope encryption built as part of the plugin connection
   flow, before real Reddit OAuth tokens are ever stored. **Done, ahead of Reddit itself** —
   built as part of the generic OAuth2 framework (`docs/auth/OAUTH2_ARCHITECTURE.md`, ADR
   0011) once the Platform Readiness Review flagged OAuth as the actual blocker; see
   `docs/reviews/OAUTH_IMPLEMENTATION_REPORT.md`.
7. **Observability** — OpenTelemetry spans on plugin calls and agent runs, wired to
   Prometheus/Grafana per `docs/observability/OBSERVABILITY.md`. Trails steps 1–6 slightly but
   ships within Phase 1, not deferred indefinitely. **Still not built as designed** — Phase 2D
   (below) added a narrower, more urgent piece instead (optional Sentry-based error tracking,
   wired into the API and every background worker) without building the full OTel/Prometheus
   stack this item describes; that remains the one item in this list with no real
   implementation yet.

**Exit criterion:** a real Reddit thread gets discovered, a reply gets drafted, you approve
it via the API, and it posts to Reddit for real. **Code-complete, not yet real-world-
verified** — every step of discover → draft → approve → publish now has a real, tested
implementation (steps 1–6 above), but nothing has exercised it against an actual connected
Reddit account with a real Anthropic API key; see each phase's implementation report's
"remaining work" section. "You approve" deliberately means via the API, not "in the
dashboard" — no frontend exists yet (Phase 2+ per `ARCHITECTURE.md` §3's layer diagram) and
building one isn't part of this phase.

## Phase 2D — Production Hardening

A cross-cutting hardening pass over the *entire* platform (foundation through Phase 2C)
before onboarding a second real user or resuming feature work — not a continuation of step
5's Conversation Finder/Content Agent work above, hence a standalone section rather than a
fourth sub-bullet nested under it. (The "2A"–"2D" letters name sub-phases of Phase 1's own
step 5 and this hardening pass respectively; the plain "Phase 2" below is the next whole
epoch and is unrelated to this lettering.)

Triggered by an adversarial Production Readiness Review
(`docs/reviews/PRODUCTION_READINESS_REVIEW.md`) of the entire platform, assuming real users
with real OAuth credentials and real publishing workflows soon. Fixed every Critical/High-
severity finding: retry was silently non-functional across every background job (Arq requires
its own `Retry` exception, not a plain re-raise — this defeated `max_tries` everywhere,
unnoticed through three prior phases' own test suites, since a job always raised *something*,
just never the type Arq actually listens for); event dispatch could double-deliver; a narrow
crash window in the publish worker could duplicate a real Reddit post; `GET /health` always
said "ok" regardless of real DB/Redis state; nothing verified a connected database was
actually migrated; zero error-tracking existed anywhere; login had no rate limiting despite
`docs/security/SECURITY.md` claiming it did; the OAuth token-refresh worker
(`app/jobs/oauth_refresh.py`) was a real, tested job nothing ever actually ran; and the
database connection-pool budget was unmanaged across six processes already summing to ~90
connections against Postgres's default 100-connection limit. See
`docs/reviews/PRODUCTION_HARDENING_REPORT.md` for what was fixed, how, tests added, and what
was deliberately left open (medium/low-severity findings — CSRF double-submit verification,
the master-key KDF, session revocation, `MembershipRole` enforcement, a dependency lockfile,
missing composite indexes, and others — plus backup/process-supervision *automation*
specifically, documented as a concrete manual procedure since the real hosting target isn't
chosen yet). See `CHANGELOG.md`'s `[0.7.0]` entry (tagged `v0.7.0-production-hardening`).

**Exit criterion:** every Critical/High-severity finding from the readiness review is fixed,
each with a regression test proving the fix, and every finding left open is explicitly
documented rather than silently dropped. **Met** — 400 tests total (up from 375), `ruff`/
`mypy --strict` clean, no architecture change, no ADR touched. Full OpenTelemetry/Prometheus
observability, a CI/CD pipeline, and backup/process-supervision automation remain explicitly
out of scope for this phase — see the hardening report's "remaining known production risks"
for the complete list of what's still open.

## Internal Beta Preparation

Turns the platform (feature-complete and hardened as of Phase 2D) into something an operator
can actually install, configure, run, and debug against real accounts — deliberately no new
business logic, per this task's own instruction. Not lettered "2E" — this isn't a further
hardening pass over existing code, it's the operational tooling and documentation layer
around it: `scripts/check_env.py` (environment doctor), `scripts/status.py` (read-only
operational dashboard), `scripts/onboard.py` (interactive org/user/project setup wizard),
`docs/examples/` (schema-validated example configs), and `docs/beta/` (Setup Guide,
Deployment Guide, Troubleshooting Guide, First Run Checklist, Known Limitations, Beta Test
Plan). See `docs/reviews/INTERNAL_BETA_READINESS_REPORT.md` and `CHANGELOG.md`'s `[0.8.0]`
entry (tagged `v0.8.0-internal-beta`).

Building tooling that actually *executes* the documented setup process, rather than just
describing it, surfaced two genuine, previously-unknown bugs sitting in this project's own
documented Quickstart since Phase 1: `scripts/migrate.py` never actually loaded `.env`
(alembic read the raw environment directly), and every script documented as
`python scripts/<name>.py` failed under the system Python since it imports `backend/app` code
that only exists in `backend/.venv`. Both fixed — see the readiness report §2.

**Exit criterion:** an operator can follow `docs/beta/FIRST_RUN_CHECKLIST.md` and reach a
running, verifiably-healthy system using their own accounts, with a documented recovery path
for every failure mode encountered while actually testing that checklist. **Met, with the one
caveat the readiness report is explicit about**: every step through project/agent/plugin
configuration was verified against a real database; the final steps (a real Reddit OAuth
connection, a real Anthropic-drafted reply, an actual publish) had not yet been exercised as
of that report — commissioning that live run end to end, with a real operator, is the
immediate next step this phase hands off to.

## Phase 2 — Full agent roster, one project

- Remaining agents: Customer Finder, Competitor Watch, Outreach Assistant, Knowledge Base
  Agent (the others are Phase 3, see below).
- Remaining plugins for ScoutSEO's actual channels: LinkedIn, Twitter/X, Search Console,
  Google Analytics, WebmasterWorld — `google_analytics` and `search_console` implement
  `MetricsQueryable`, not `Searchable` (see `docs/plugins/PLUGIN_ARCHITECTURE.md`).
- Orchestrator: the daily cron cycle and `project.daily_cycle.completed`-triggered Morning
  Brief assembly — no sequencing config to build, since each new agent declares its own
  event subscriptions in its own package.
- Frontend: Morning Brief view, Knowledge Base explorer, the generic
  `DynamicConnectionForm`-based plugin connection management (one component serving every
  plugin added from here on, per `docs/decisions/0009-plugin-config-schema-dynamic-ui.md`).

**Exit criterion:** GrowthOS runs unattended every morning for ScoutSEO and the Morning
Brief is something you'd actually open before coffee, not something you'd ignore.

## Phase 3 — Second project + deferred agents

- Onboard a second SaaS business as a second Project — this is the real test of the
  "nothing hardcoded for ScoutSEO" constraint from `ARCHITECTURE.md`. If this requires
  touching `agents/` or `backend/` core code, Phase 2 had a leak and it gets fixed here.
- **Analytics Agent** and **CRM Assistant** — deferred to this phase deliberately (see
  §Deferred) because they depend on knowledge base and customer data volume that doesn't
  exist until Phase 1–2 have been running for a while.
- Remaining plugins: Slack, Discord, Email, GitHub, generic CRM.

**Exit criterion:** two unrelated SaaS products both run on GrowthOS with zero
project-specific code changes.

## Phase 4 — Multi-tenant activation (only if you decide to sell GrowthOS)

Everything here was deliberately built cheaply-activatable in Phase 0–1 rather than bolted
on later — see `docs/decisions/0001-multi-tenancy.md`. **Activated** — confirmed cheap to
activate as designed: no schema rework was needed, only new tables/routes/jobs alongside the
existing model.

- Signup flow — **Done.** `POST /api/v1/auth/register` is now a genuine public signup path
  (see `app/services/auth_service.py`'s updated docstring), not the solo-operator bootstrap
  it was through Phase 3. Org invitations / roles beyond a single owner remain **not done** —
  a real gap for a team account, not yet needed for the single-owner-per-org model this
  launch targets.
- Billing integration — **Done**, against Polar (not Stripe — Stripe does not currently
  onboard solo-founder/individual accounts in India). One plan, 7-day trial, card required
  upfront. See `docs/billing/BILLING_ARCHITECTURE.md` for the full design and what's still
  missing before a real public launch (a frontend, chiefly — none exists yet).
- Per-org resource limits and rate limiting — **Partially done.** The subscription
  entitlement gate (`app/core/entitlements.py`) blocks all paid plugin/LLM usage for an
  unentitled org, wired into both API routes and background jobs (agent runs, event-triggered
  runs, publish) so a canceled org's *scheduled* work stops too, not just its API access. Real
  per-plan usage quotas (distinct from each plugin's own rate limiter) are not built — see
  `docs/billing/BILLING_ARCHITECTURE.md`'s "still missing" section.
- Tenant isolation audit (see `docs/security/SECURITY.md`) — **Not done.** Flagged explicitly
  in `docs/billing/BILLING_ARCHITECTURE.md` and `app/api/deps.py`'s `require_project_access`
  docstring as the next thing worth a dedicated pass, now that real strangers hold accounts.

**Exit criterion:** a second, unrelated human can sign up, connect their own plugins, and
run GrowthOS for their own business with zero visibility into your data. **Not yet verified
end-to-end** — the backend flow is code-complete and tested, but no frontend exists for a real
second human to actually use, and no live Polar account has been connected outside sandbox.

## Deferred, with reasoning

| Item | Why deferred |
|---|---|
| Analytics Agent | Needs enough historical `knowledge_items`/`content_items` volume to find real patterns. Building it against empty tables means designing against guesses. |
| CRM Assistant | Depends on Customer Finder and Outreach Assistant having run long enough to produce real relationship state worth assisting with. |
| Team accounts (org invitations, roles beyond owner) | Public signup + billing (Phase 4) are now activated; multi-user-per-org access is the remaining, not-yet-needed piece of the original solo-first deferral — single-owner-per-org is sufficient for launch. |
| Kubernetes | Docker Compose is correct for one operator's workload. Revisit only if/when Phase 4 activates and concurrent-tenant load actually requires it — see `docs/scalability/SCALABILITY.md`. |
| Mobile app | Nothing in the vision requires it yet; the dashboard is a morning-coffee check-in, not a mobile-first workflow. |
| Fine-tuned/self-hosted models | Provider abstraction (Claude + OpenAI) is deliberately in place so this is a future swap, not a rewrite, if cost or latency ever demands it. |
| Plugin sandboxing/isolation | Current trust model assumes first-party, reviewed plugin code only — a hard prerequisite before accepting any plugin not personally written/reviewed, not before then. See `docs/plugins/PLUGIN_ARCHITECTURE.md` §Trust model. |
| Dedicated event broker (Kafka/NATS) | The transactional-outbox-plus-Arq approach (`ARCHITECTURE.md` §7) is deliberately chosen over a dedicated broker at this scale. Revisit only if event volume or fan-out breadth grows by orders of magnitude — see `docs/scalability/SCALABILITY.md`. |

## Non-goals (permanent, not just deferred)

- **Autonomous publishing.** GrowthOS will never post, message, or publish without a human
  approval transition, at any phase, for any plugin. This is not a v1 limitation — see
  `ARCHITECTURE.md` §8.
- **Being a generic marketing automation platform.** GrowthOS is opinionated about the
  human-in-the-loop model; if that constraint is ever removed to chase a broader market,
  it's a different product.
