# Billing Architecture (Phase 4)

**Status:** Implemented — tiered launch pricing, 7-day trial, Polar as the payment processor.
See `docs/reviews/` for the implementation report once written, `ROADMAP.md`'s Phase 4 entry,
and `docs/database/SCHEMA.md`'s `subscriptions` table note.

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

## Tiered launch pricing

Every org's *feature set* is identical regardless of price paid — entitlement stays binary
(active/trialing or not, see `app/core/entitlements.py`). What varies is which of three Polar
Products a checkout session is created against:

| Tier | Key | Price | Capacity |
|---|---|---|---|
| Founding | `founding` | $9/month | First 5 organizations ever to check out |
| Early | `early` | $19/month | Next 10 |
| Standard | `standard` | $29/month | Everyone after that, unlimited |

No discount codes exist anywhere in this flow — a customer never sees or enters one. Instead,
`BillingService._resolve_product_id` (`app/services/billing_service.py`) counts how many
organizations already have a `subscriptions` row (`SubscriptionRepository.count_all()` —
deliberately includes canceled rows, since a founding-tier org that cancels doesn't free its
spot for someone else) and maps that count to a tier via `app/core/pricing.py`'s pure
`tier_for_count`. The resulting Polar Product id is passed to `checkouts.create_async` exactly
like the single-plan flow did — Checkout, trial, and webhook sync are otherwise unchanged.

Tier assignment is **sticky**: if an org already has a subscription row (even a canceled one,
e.g. it abandoned an earlier checkout and is trying again), `_resolve_product_id` reuses that
row's `polar_product_id` rather than recomputing — both because the price should be permanent
once assigned, and to avoid the org's own row inflating the count against itself.

The same counter powers a public, unauthenticated `GET /api/v1/billing/pricing-tiers`
(`app/core/pricing.py`'s `tier_statuses`) — the landing page's live "spots left" display. It's
read-only and makes no Polar call; it reads the same `subscriptions` table
`_resolve_product_id` counts, so the two can never disagree about how many spots are taken.

This does mean three Products must exist in the Polar Dashboard instead of one — see Setup
below — and there's a small, accepted race window if two signups complete Checkout
concurrently right at a tier boundary (both could read the same pre-increment count and land
in the same tier one spot over capacity). Not worth locking around at expected launch volume;
revisit if it ever actually happens.

Splitting into unlimited future tiers still isn't done — see the original reasoning below,
which continues to apply beyond these three fixed launch tiers: adding a fourth means a new
Polar Product + a new tier entry in `app/core/pricing.py`'s `PRICING_TIERS`, not a
rearchitecture. Nothing in `BillingService`, the `subscriptions` table, or
`app/core/entitlements.py` is plan-aware beyond product-id selection at checkout time.

## No-card 7-day trial

Signup itself starts a 7-day trial — no card, no Polar Checkout involved at all yet.
`app/core/entitlements.py`'s `is_org_entitled` treats an org with no `subscriptions` row as
entitled until `NO_CARD_TRIAL_DAYS` (7) after `Organization.created_at`, computed on the fly
rather than stored on its own column — no migration, and it can never drift out of sync with
when the org actually signed up. `no_card_trial_ends_at()` is the one place that math happens;
`GET /orgs/{org_id}/billing/status` (`app/api/v1/billing.py`) calls the same function so the
dashboard's trial countdown can never disagree with what actually gates access.

Once that window elapses without a completed Checkout, the org drops out of
`is_org_entitled` — same 402 (`SubscriptionRequiredError`) as `past_due`/`canceled`, and the
dashboard prompts to subscribe. Checkout at that point (or any time, if someone wants to lock
in a tier before spots run out — see "Tiered launch pricing" below) is `allow_trial=False`
(`BillingService.create_checkout_session`): the free period already happened before Checkout
ever ran, so a second, Polar-side trial stacked on top would double the free period. This is
enforced at the checkout-request level specifically so it holds even if a Polar Product still
has a trial period configured on its own (see Setup below) — belt-and-suspenders, not reliant
on remembering a dashboard setting.

This still leaves the real cost-exposure question card-required trials existed to solve: every
plugin's API access is genuinely metered upstream (X API v2 is pay-per-use — see
`plugins/twitter/README.md`), so a no-card trial is real, uncapped cost exposure with no
revenue behind it until someone converts. Accepted for now in exchange for a lower-friction
signup; a per-org usage cap during the no-card window specifically (tighter than the
subscribed-tier limits) is the natural mitigation if abuse becomes a real problem — not built
yet, see "What's still missing" below.

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
   `app/services/auth_service.py`'s docstring), and creates no subscription — but the org is
   immediately entitled via the no-card trial (see above), not gated on checkout the way it
   used to be.
2. **Checkout** (`POST /api/v1/orgs/{org_id}/billing/checkout-session`) — optional during the
   no-card trial (locks in a tier early), required once it elapses.
   `BillingService.create_checkout_session` calls Polar's `checkouts.create_async`, passing
   `external_customer_id=str(org.id)`. This is the load-bearing detail: Polar links its own
   Customer record back to this org via that field, so every later webhook for this
   subscription carries it on `subscription.customer.external_id` — no separate "pending
   checkout" state needs tracking between session creation and webhook arrival.
3. **No Polar-side trial** — `allow_trial=False` on every Checkout request now (see above);
   whatever trial duration a Polar Product still has configured on it never applies. Checkout
   always charges immediately.
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
   read the `subscriptions` row directly (falling back to the no-card trial window when there
   isn't one yet — see above); no Polar call, no `billing_service` import. Wired into:
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
2. Create **three** subscription Products, one per launch tier (see "Tiered launch pricing"
   above) — $9, $19, and $29/month. No trial needs configuring on them — the free 7 days now
   happens entirely before Checkout (see "No-card 7-day trial" above), and `allow_trial=False`
   on every Checkout request means a Product-level trial wouldn't apply even if left on from
   before. Note their Product ids → `POLAR_PRODUCT_ID_TIER1` (founding, $9),
   `POLAR_PRODUCT_ID_TIER2` (early, $19), `POLAR_PRODUCT_ID` (standard, $29).
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
- **A real Polar account and three Products**, not sandbox — §Setup above is unstarted in any
  real environment as of this writing.
- **Per-plan usage quotas.** Today's only usage ceiling is each plugin's own rate limiter
  (e.g. Twitter's 60 req/15min, shared across whatever org happens to be calling it in-process
  — see `plugins/twitter/README.md`'s "Known limitation — process-local only"). There is no
  per-org daily/monthly cap tied to the subscription plan yet; the three launch tiers differ
  only in price, not feature set or usage limits — revisit once real usage data shows it's
  needed. This matters more now that signup grants a full 7 days of access with no card on
  file at all (see "No-card 7-day trial" above) — a tighter cap specifically during that
  window, before any payment method exists, is the natural first mitigation if trial abuse
  becomes a real cost problem.
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
