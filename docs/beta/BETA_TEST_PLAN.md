# Recommended Beta Test Plan

A phased plan for running GrowthOS against your own real accounts, increasing autonomy only
as each phase actually earns it. The point of this beta isn't to prove the code works — the
test suite already does that (400 tests, `docs/reviews/PRODUCTION_HARDENING_REPORT.md`) — it's
to prove the *system*, running against real external services with real judgment calls,
behaves the way you want it to. Nothing here has been exercised against a real Reddit account
yet; that's exactly what this plan is for.

## Phase 1 — Wiring check (day 1, no autonomy)

**Goal:** prove the full discover → draft → approve → publish loop works at all, once,
end to end.

- Follow `docs/beta/FIRST_RUN_CHECKLIST.md` exactly.
- Use a low-stakes subreddit you're comfortable posting a slightly-imperfect reply in — not
  your primary marketing channel yet.
- Trigger every agent run manually (`POST .../runs/trigger`) — no `schedule_cron` set yet.
- Read the one draft it produces in full. Approve it only if you'd have posted those exact
  words yourself.
- **Success criterion:** one real Reddit comment, posted by GrowthOS, that you're genuinely
  glad exists.
- **Stop and investigate, don't push forward, if:** the draft is off-topic, factually wrong,
  or generically AI-sounding in a way `banned_phrases` should have caught — tune
  `docs/examples/content-agent-config.json`'s config before doing anything else.

## Phase 2 — Manual-everything, higher volume (week 1)

**Goal:** build a real sample size of drafts to judge quality and tune thresholds, still with
zero unsupervised action.

- Still trigger runs manually, but do it daily, across 2-4 subreddits relevant to you.
- Review **every single draft** — approve, reject with a reason, or archive. Never skip this
  step, even for drafts you don't intend to use.
- Track informally (a spreadsheet is fine): how many drafts were approve-worthy as-is, how
  many needed a mental edit you couldn't make (since there's no edit-then-approve flow yet —
  see `docs/beta/KNOWN_LIMITATIONS.md`), how many were clearly wrong.
- Adjust `min_confidence_for_reply` and `min_score_to_save` based on what you're seeing —
  raise them if too much low-quality material is reaching review; lower them if
  Conversation Finder is finding too little.
- **Success criterion:** a consistent (even if not perfect) hit rate you can describe in one
  sentence — e.g. "about 2 in 3 drafts are approve-worthy with no changes I'd want to make."

## Phase 3 — Scheduled discovery, still manual approval (weeks 2-3)

**Goal:** let discovery run unattended; keep the approval gate fully manual.

- Set `conversation-finder`'s `schedule_cron` (e.g. once daily) — Content Agent already reacts
  automatically to whatever it finds, no change needed there.
- Check in at least once a day: `python scripts/status.py`, review anything in
  `pending_review`.
- Watch the event-dispatch backlog and recent `agent_runs` for failures — this is also a good
  window to confirm you'd actually notice a crashed worker (see
  `docs/beta/KNOWN_LIMITATIONS.md`'s operational gaps) before trusting this phase for longer
  stretches unattended.
- **Success criterion:** at least a week where nothing broke silently, and you never felt
  compelled to intervene outside your normal daily check-in.
- **Roll back to Phase 2** (disable the schedule) if: failures pile up unnoticed for more than
  a day, or you find yourself uncomfortable with what Conversation Finder is surfacing.

## Phase 4 — Steady state (week 4+)

**Goal:** this is now a normal part of your workflow, not an experiment.

- Continue reviewing every draft before it publishes — this project's own non-goals
  (`ROADMAP.md`) state autonomous publishing without human approval will **never** exist, at
  any phase, for any plugin. This isn't a beta limitation to graduate out of; it's permanent.
- Set `SENTRY_DSN` if you haven't already (`docs/beta/DEPLOYMENT_GUIDE.md`) — at this point
  you're trusting the system to run genuinely unattended between check-ins, and want to know
  immediately if something breaks rather than discovering it days later.
- Set up real backups and process supervision if you haven't (`docs/beta/DEPLOYMENT_GUIDE.md`)
  — steady-state unattended operation is exactly the scenario those protect against.
- Periodically revisit `docs/beta/KNOWN_LIMITATIONS.md` — several items there (session
  revocation, role-based access, automated backups) matter more the longer this runs and the
  more it becomes load-bearing for you.

## What to monitor throughout, at every phase

- `python scripts/status.py` — plugin connection health, recent run outcomes, pending
  reviews, event-dispatch backlog, approved-but-failing publishes.
- `GET /api/v1/projects/{project_id}/content-items/{id}/publish-attempts` for anything that
  ever shows a `publish_error` — understand *why* before just retrying blindly.
- The `audit_log` table (or a future API surface for it) for a full account of every
  approve/reject/archive/publish decision, if you ever need to reconstruct what happened.

## When to consider the beta "done" and move toward wider use

Not a fixed date — a judgment call based on: a stable draft-quality hit rate you're satisfied
with, at least a few weeks of Phase 3/4 with no unnoticed failures, and every item in
`docs/beta/KNOWN_LIMITATIONS.md`'s "Operational" section addressed (backups, process
supervision, monitoring) if you intend to run this genuinely unattended for extended periods.
See `ROADMAP.md` for what comes after — Phase 2 (full agent roster) and Phase 3 (a second
project) both assume the loop this beta validates is already trustworthy.
