# Billing Architecture (Phase 4)

**Status:** Implemented — one plan, 7-day trial, Polar as the payment processor. See
`docs/reviews/` for the implementation report once written, `ROADMAP.md`'s Phase 4 entry, and
`docs/database/SCHEMA.md`'s `subscriptions` table note.

## Why Polar, not Stripe

Stripe does not currently allow solo-founder/individual accounts in India to self-serve
onboard — a real, personal constraint for this project, not a technical preference. Polar
(<https://polar.sh>) is a merchant-of-record payments platform: self-serve account creation
regardless of business-registration status, and — because it's merchant of record, not a
processor — Polar itself handles tax/VAT compliance across jurisdictions rather than pushing
that onto this codebase. The generic pieces of this design (the `subscriptions` table,
`app/core/entitlements.py`) don't know or care which processor is behind them; only
`app/services/billing_service.py` talks to Polar's API, the same "one boundary module"
principle `app/core/oauth/client.py` follows for OAuth providers.

## Why one plan, not tiers, at launch

Splitting into tiers before a single paying customer exists means guessing what a "higher"
tier should even contain. Ship one plan, learn what customers actually ask for, then add a
tier as a new Polar Product + a new `STRIPE_PRICE_ID`-equivalent config value — not a
rearchitecture. Nothing in `BillingService`, the `subscriptions` table, or
`app/core/entitlements.py` is plan-aware; entitlement is binary (active/trialing or not), so
adding a second plan later touches Polar Dashboard config and, at most, a small amount of
plan-selection UI — never the gating logic itself.

## Why card-required at signup, not a no-card trial

Every plugin's API access is now genuinely metered upstream — X API v2 moved to pay-per-use
pricing (see `plugins/twitter/README.md`) — so a free trial that lets an anonymous signup make
unlimited plugin calls is a direct, uncapped cost exposure with no revenue behind it.
Requiring a card at Checkout (Polar's Checkout Session, not a custom form — card data never
touches this codebase) is the standard, low-effort mitigation: a trial-abuser still has to
supply a real payment method.

## Data model

`subscriptions` — one row per org (`unique(org_id)`), org-level like `memberships`, not
project-level. Mirrors Polar's own subscription object; `status` is written only by webhook
events, never computed locally. See `docs/database/SCHEMA.md`'s `subscriptions` note and
`app/models/billing.py`.

`SubscriptionStatus` (`incomplete | trialing | active | past_due | canceled`) is a deliberate
subset of Polar's own status enum (which also has `unpaid`, `paused`, `incomplete_expired`) —
anything outside this subset is treated conservatively as `canceled` (not entitled) by
`BillingService._parse_status` rather than growing the enum ahead of a real need.

`ENTITLED_STATUSES = {trialing, active}` — the only two statuses that unlock paid features.
Kept next to the enum it's derived from in `app/models/billing.py` so the two can never
silently drift apart.

## The Checkout → webhook → entitlement flow

1. **Signup** (`POST /api/v1/auth/register`) creates the org + owner user — this is now a
   genuine public signup path (previously a solo-operator bootstrap, see
   `app/services/auth_service.py`'s docstring), but creates no subscription. The org exists,
   unentitled, until checkout completes.
2. **Checkout** (`POST /api/v1/orgs/{org_id}/billing/checkout-session`) —
   `BillingService.create_checkout_session` calls Polar's `checkouts.create_async`, passing
   `external_customer_id=str(org.id)`. This is the load-bearing detail: Polar links its own
   Customer record back to this org via that field, so every later webhook for this
   subscription carries it on `subscription.customer.external_id` — no separate "pending
   checkout" state needs tracking between session creation and webhook arrival.
3. **Trial configuration lives on the Polar Product**, not passed per-checkout — set the
   7-day trial when creating the Product in the Polar Dashboard (see "Setup" below);
   `allow_trial=True` on the Checkout request just permits it to apply.
4. **Webhook** (`POST /api/v1/billing/webhook`, one fixed URL, not org-scoped — the same
   reasoning `app/api/v1/oauth.py`'s callback route documents for OAuth providers) —
   `BillingService.handle_webhook_event` verifies the signature via `polar_sdk.webhooks.
   validate_event` (Standard Webhooks spec), then syncs the `subscriptions` row for every
   subscription-lifecycle event Polar sends (`subscription.created`, `.updated`, `.active`,
   `.canceled`, `.past_due`, `.uncanceled`, `.revoked` — Polar fires a distinct event per
   transition rather than one generic "changed" event; all are synced identically here,
   re-reading the Subscription's current state rather than branching per event type). Every
   other event type (`checkout.*`, `customer.*`, `order.*`, ...) is logged and ignored.
5. **Entitlement gate** (`app/core/entitlements.py`) — `is_org_entitled`/`require_org_entitled`
   read the `subscriptions` row directly; no Polar call, no `billing_service` import. Wired
   into:
   - `POST .../plugin-connections` (`app/api/deps.py`'s `require_active_subscription`) — the
     act of connecting an account is where paid, metered API usage starts.
   - `POST .../agent-configs/{key}/runs/trigger` (same dependency) — a manual run spends real
     LLM tokens and plugin API calls.
   - `run_scheduled_agent` (`app/jobs/agent_runs.py`) and `run_agent_for_event`
     (`app/jobs/events.py`) — **the reason this couldn't just be an HTTP-layer check**: a
     scheduled/subscription-triggered agent run has no HTTP request to reject. Without this,
     a canceled org's cron-scheduled Conversation Finder or event-triggered Content Agent
     would keep spending money indefinitely. Both check `is_org_entitled` at the top of the
     job body and skip (logged, not raised) if the org isn't entitled.
   - `publish_content_item` (`app/jobs/publish.py`) — a human already approved the item, but
     if the subscription lapsed between approval and this job running, the item is left
     `approved` with a clear `publish_error` rather than posted — no `Retry` raised, since
     retrying won't help until the org resubscribes.
6. **Customer Portal** (`POST /api/v1/orgs/{org_id}/billing/portal-session`) — self-serve
   cancel / update card / view invoices, entirely on Polar's hosted page. 404s if the org has
   never completed a checkout.

## Setup (operator, per environment)

1. Create a Polar account at <https://polar.sh> and a Polar Organization (Polar's own
   multi-tenant concept for *sellers* — not to be confused with this platform's own
   `organizations` table, which is for *customers*).
2. Create a subscription Product with the 7-day trial configured on it. Note its Product id
   → `POLAR_PRODUCT_ID`.
3. Get an access token (Polar Dashboard → Settings → API) → `POLAR_ACCESS_TOKEN`.
4. Register a webhook endpoint pointing at
   `{OAUTH_CALLBACK_BASE_URL}/api/v1/billing/webhook`, subscribed at minimum to the
   `subscription.*` events. Note its signing secret → `POLAR_WEBHOOK_SECRET`.
5. Leave `POLAR_SERVER=sandbox` (the default) until ready to take real payments — sandbox is a
   fully separate Polar environment with its own test data, so nothing here risks a real
   charge until this is explicitly set to `production`.
6. See `.env.example` for the exact variable names.

## What's still missing before this is a real, public launch

- **A frontend.** None exists in this repo. Polar's Checkout and Customer Portal are hosted
  (zero custom UI needed for payment itself), but signup, login, connecting a plugin account,
  and the approval inbox all still need *some* UI — even a minimal one. This is the most
  honest, largest gap: everything above is reachable today only via direct API calls.
- **A real Polar account and Product**, not sandbox — §Setup above is unstarted in any real
  environment as of this writing.
- **Per-plan usage quotas.** Today's only usage ceiling is each plugin's own rate limiter
  (e.g. Twitter's 60 req/15min, shared across whatever org happens to be calling it in-process
  — see `plugins/twitter/README.md`'s "Known limitation — process-local only"). There is no
  per-org daily/monthly cap tied to the subscription plan yet; acceptable for a single launch
  plan with one tier, revisit once tiers exist or real usage data shows it's needed.
- **Tenant isolation audit.** `require_project_access`'s 403-vs-404 choice (see
  `app/api/deps.py`) was reasoned about for a single-operator system; now that strangers hold
  real accounts, it's a genuine question worth a dedicated pass, not changed reactively here —
  see `ROADMAP.md`'s Phase 4 checklist ("tenant isolation audit").
- **Terms of Service / Privacy Policy.** Not written. Needed both for Polar's own onboarding
  and because this platform now handles other people's data and money.
- **LinkedIn/Reddit billing.** Today's plan gates on subscription status only, not which
  plugins are connected — LinkedIn and Reddit already ride the same gate for free once a
  customer connects them (see `plugins/linkedin/README.md`, `plugins/reddit/README.md`), no
  billing-code changes needed. What's still open is whether a customer connecting all three
  should cost more than one — a pricing question, not an engineering one.
