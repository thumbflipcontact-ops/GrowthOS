# Troubleshooting Guide

**Start here, always:** `python scripts/check_env.py` and `python scripts/status.py`. Most
problems below are exactly what one of these two commands is designed to surface directly,
with a specific remediation hint — read their output before reading further in this doc.

## Installation / scripts

### `ModuleNotFoundError: No module named 'pydantic_settings'` (or similar) running a script

You're running a script that imports `backend/app` code under a Python interpreter that
isn't `backend/.venv`'s — that package is only installed there. `check_env.py`, `status.py`,
`onboard.py`, and `seed.py` all auto-detect this and re-exec themselves under the right
interpreter (`scripts/_bootstrap.py`); if you hit this anyway, run the script explicitly via
`backend/.venv/Scripts/python.exe scripts/<name>.py` (Windows) or
`backend/.venv/bin/python scripts/<name>.py` (macOS/Linux).

### `sqlalchemy.exc.NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:driver` running `scripts/migrate.py`

`DATABASE_URL` wasn't actually available to the `alembic` subprocess — it fell back to
`alembic.ini`'s placeholder URL. `scripts/migrate.py` loads `.env` itself before invoking
`alembic`; if you still hit this, confirm a `.env` file exists at the repo root (not
`backend/.env`) and actually contains `DATABASE_URL=...`.

### A script hangs forever at a password prompt, no error

Known issue in mintty-based terminals (Git Bash's default on Windows) — `getpass` reads
directly from the Win32 console, which mintty doesn't provide, so the read blocks forever
instead of erroring. `onboard.py` detects this (`MSYSTEM` env var) and falls back to visible
input automatically. If you hit this in a different interactive script, switch to PowerShell,
cmd.exe, or Windows Terminal, or interrupt (Ctrl+C) and try again there.

## Environment / connectivity

### `check_env.py` reports Database: fail

Postgres isn't running, or `DATABASE_URL` is wrong. For a Docker-free local instance:
`cd backend && .venv/Scripts/python scripts/dev_postgres.py` — it prints the exact
`DATABASE_URL` to use (it changes every restart, since it binds a random local port).

### `check_env.py` reports Redis: fail

Same idea — Redis isn't running, or `REDIS_URL` is wrong. A local `redis-server`, or
`docker compose up redis` from `docker/docker-compose.yml`, both work.

### `check_env.py` reports Migrations: fail

Run `python scripts/migrate.py`. If it still fails after that, `check_env.py`'s error message
includes the actual database error — a `relation "..." does not exist` error anywhere else in
the app (not from check_env.py) means the same thing: migrations haven't been run against the
database this process is actually connected to.

### `GET /health` returns 503

The response body's `checks` object says which dependency failed (`database` or `redis`) and
why — same fixes as the two items above.

## Login / auth

### `429 too_many_requests` on `POST /auth/login`

Rate limiting (per source IP: 10 attempts / 5 min; per account: 5 attempts / 15 min — see
`docs/reviews/PRODUCTION_HARDENING_REPORT.md` §1.7). Wait for the window to pass. If this
fires on your very first real login attempt, you're likely also hitting it from automated
retries (a script looping) — check for that before assuming something's broken.

### OAuth callback redirects with `?connected=<plugin>&error=...` instead of success

The signed state token expired (10-minute window from `POST .../oauth/start`) or was
otherwise rejected. Just call `.../oauth/start` again and complete the browser flow within
10 minutes this time.

## Conversation Finder finds nothing

In order of likelihood:
1. The Reddit plugin connection's `status` isn't `connected` yet — check
   `python scripts/status.py`; if it says `expired` or `error`, re-run
   `POST .../plugin-connections/reddit/oauth/start`.
2. `subreddits` in the connection's `config` is empty — `search()` returns nothing until you
   set it (`docs/examples/reddit-plugin-connection.json`).
3. `keywords` in the agent config don't match anything currently active in your configured
   subreddits — try broader terms, or a subreddit you know is currently discussing your topic.
4. `lookback_hours` is too short for how active the subreddit is.

## Content Agent never drafts anything, even though Knowledge Items exist

1. Confirm `content_agent`'s `agent_configs` row has `enabled: true`
   (`python scripts/status.py` shows this).
2. Check `worker-events` is actually running — event dispatch (and therefore Content Agent's
   trigger) depends on it. `python scripts/status.py`'s "Event dispatch backlog" section
   growing steadily, never shrinking, means it isn't.
3. The triggering `knowledge_item`'s `confidence` may be below `content_agent`'s
   `min_confidence_for_reply` — this is a deliberate skip, not a bug; check the
   `knowledge-items` API response's `confidence` field against your configured threshold.

## A draft never advances past `draft` status (stuck, never reaches `pending_review`)

This is the self-check failing — a real, currently-unsurfaced-in-any-UI gap (see
`docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md` §5). Check the triggering
`agent_runs` row's `summary.details.self_check_reasons` (via `GET .../agent-configs/
content_agent/runs`) — almost always either the draft exceeded `max_reply_length` or
contained one of `banned_phrases`. There's no automatic retry; a human has to notice via this
query today.

## An approved item stays `approved` forever with `publish_error` set

1. Read `publish_error` directly, and the full history:
   `GET .../content-items/{id}/publish-attempts`.
2. Common causes: the Reddit connection expired between approval and publish (reconnect via
   OAuth, then `POST .../content-items/{id}/retry-publish`); Reddit rate-limited the request
   (wait, then retry); the post was removed/the account is shadowbanned (a real account-level
   Reddit issue, not a GrowthOS bug — check by logging into Reddit directly).
3. Automatic retries (up to 3, exponential backoff) already happened by the time you see this
   — `retry-publish` triggers one more attempt manually once you believe the underlying cause
   is fixed.

## Nothing seems to be happening at all

`python scripts/status.py` is the fastest way to see the whole picture: are there any
`agent_runs` at all (schedule/trigger not actually firing?), is the event-dispatch backlog
growing (a worker process is down?), are there `content_items` stuck somewhere unexpected.
If `status.py` shows nothing whatsoever for a project you know has plugin connections and
agent configs, verify all six processes from `docs/deployment/DEPLOYMENT.md` are actually
running — a missing `worker-agents` or `scheduler` process produces exactly this symptom.
