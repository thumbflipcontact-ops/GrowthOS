# Known Limitations (Internal Beta)

Written for you, the operator, running this against your own real accounts — not a developer
audience. Each item says what to actually expect and, where relevant, what to do about it.
See `docs/reviews/PRODUCTION_HARDENING_REPORT.md` §4 for the equivalent developer-facing list
with severity ratings and file references.

## About publishing, specifically

- **No undo.** Once GrowthOS posts a reply to Reddit, it's live under your account exactly
  like if you'd typed it yourself. Read every draft before approving it — see
  `docs/beta/BETA_TEST_PLAN.md`'s recommendation to review everything for at least the first
  couple of weeks, no exceptions.
- **The self-check is a blunt safety net, not a quality filter.** It only catches "too long"
  and "contains one of your banned phrases" — it says nothing about whether a draft is
  actually good, accurate, or on-brand. That judgment is entirely yours at approval time.
- **A draft that fails the self-check silently disappears from view.** It stays in `draft`
  status forever with no alert anywhere — see `docs/beta/TROUBLESHOOTING_GUIDE.md`'s entry on
  this. Check agent run summaries periodically if you want to know how often it's happening.
- **Reddit itself can still reject or shadow-limit a post** for reasons entirely outside
  GrowthOS (account age/karma, subreddit-specific spam filters). A `publish_error` doesn't
  always mean GrowthOS did anything wrong.

## Reliability

- **Retries are real but not infinite.** A transient failure (network blip, Reddit rate
  limit) is retried automatically up to 3 times with backoff. After that, an item sits
  `approved`+`publish_error` until you manually retry
  (`POST .../content-items/{id}/retry-publish`) — it will not resolve itself.
- **A background worker crashing is not automatically visible to you** unless you've set
  `SENTRY_DSN` (see `docs/beta/DEPLOYMENT_GUIDE.md`) or you happen to check
  `python scripts/status.py`. No full monitoring/alerting stack exists yet.
- **Nothing restarts a crashed process for you.** If a worker dies, it stays dead until you
  (or a process supervisor you've set up yourself) notice and restart it.

## Security

- **Rate limiting is per-process, not distributed.** If you ever run more than one backend
  instance, each enforces login limits independently — fine at solo-operator scale, a real
  gap the moment it isn't.
- **No session revocation.** If you're worried a session was compromised, the only fix today
  is rotating `SECRET_KEY`, which logs out every session, not just the one in question.
- **CSRF double-submit verification isn't implemented**, despite a cookie being set for it —
  `SameSite=Lax` covers the common case, but this is a known, tracked gap.
- **No multi-user roles yet.** Every account that's a member of your org has full owner-level
  access — there's no "member" tier with reduced permissions, even though the field exists.
  Fine while it's just you; don't add teammates expecting reduced access yet.

## Operational

- **Backups are manual.** Nothing automatically backs up your database. See
  `docs/beta/DEPLOYMENT_GUIDE.md` for the exact `pg_dump` command — actually run it, on a
  schedule, or accept that a disk failure means losing everything, including every knowledge
  item and content item you've accumulated.
- **No automatic restart on crash.** See `docs/beta/DEPLOYMENT_GUIDE.md`'s "process
  supervision" note — you need to set this up yourself.
- **The Docker Compose deployment path has never been run end to end.** If you use it and hit
  a problem, you're the first to find it — the Docker-free path this guide otherwise
  documents is what's actually been exercised.
- **No CI pipeline.** Nothing automatically re-runs the test suite when code changes; if you
  modify anything yourself, run `python scripts/lint.py` and the test suite manually.

## Feature scope

- **Reddit only.** No LinkedIn, X/Twitter, Slack, Discord, or email — one plugin exists.
- **Reply drafts only.** Content Agent doesn't draft outreach messages or long-form articles,
  only replies to discovered Reddit threads.
- **No frontend.** Everything in this beta is driven via the HTTP API directly (`curl`, or
  any HTTP client) — there is no dashboard to click through. `python scripts/status.py` is
  the closest thing to a status view that exists today.
- **No scheduling automation for a "morning brief" or similar** — that's a later-phase
  feature (see `ROADMAP.md` Phase 2).
- **Single project tested in depth.** Nothing has been run against two simultaneous,
  unrelated projects — the schema and code are designed to support it, but it hasn't been
  exercised as thoroughly as the single-project path documented in this beta's checklists.

## What genuinely hasn't been verified yet

Everything above has been built and unit/integration tested against real infrastructure
(a real Postgres, real migrations, the actual onboarding/status/check-env tooling) as part of
preparing this beta. What has **not** been exercised as of this writing: an actual real Reddit
account posting a real comment, and an actual real Anthropic API call drafting a real reply,
end to end, outside of a controlled test. That is the explicit purpose of this beta — see
`docs/beta/BETA_TEST_PLAN.md`.
