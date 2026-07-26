# First Run Checklist

A literal, in-order checklist from a fresh git clone to your first real Reddit post, drafted
by Content Agent and published only after you explicitly approved it. Each step names the
exact command or action — see `docs/beta/SETUP_GUIDE.md` for the *why* behind each one, and
`docs/beta/TROUBLESHOOTING_GUIDE.md` if a step doesn't behave as described.

## Setup

- [ ] `python scripts/setup.py` — provisions `backend/.venv`, copies `.env.example` → `.env`.
- [ ] Start Postgres (`backend/.venv/Scripts/python scripts/dev_postgres.py` or a real
      instance) and Redis. Leave both running.
- [ ] Fill in `.env`: `DATABASE_URL`, `REDIS_URL`, `ANTHROPIC_API_KEY`, `SECRET_KEY`,
      `CREDENTIAL_MASTER_KEY` (generate the last two with
      `python -c "import secrets; print(secrets.token_urlsafe(32))"`, two different values).
- [ ] `python scripts/check_env.py` — **must show 0 failures** before continuing (warnings
      about Reddit/Anthropic credentials are expected at this point).
- [ ] `python scripts/migrate.py`
- [ ] `python scripts/check_env.py` again — Migrations should now show `[OK]`.

## Your account

- [ ] `python scripts/onboard.py` — creates your org, your login, and your first project.
      **Save the printed project id** — every command below needs it.

## Reddit

- [ ] Register an app at <https://www.reddit.com/prefs/apps> (type: script or web app,
      redirect URI `http://localhost:8000/api/v1/oauth/reddit/callback` for local use).
- [ ] Add `REDDIT_OAUTH_CLIENT_ID` / `REDDIT_OAUTH_CLIENT_SECRET` to `.env`.
- [ ] `python scripts/check_env.py` — Reddit OAuth credentials should now show `[OK]`.

## Start the application

- [ ] Start all six processes (backend, scheduler, 4 workers) — see
      `docs/deployment/DEPLOYMENT.md`'s "Non-Docker deployment" for exact commands, one per
      terminal.
- [ ] `curl http://localhost:8000/api/v1/health` returns `{"status": "ok", ...}`.
- [ ] `python scripts/status.py` runs without error (expected: your project with no
      connections/configs/runs yet).

## Connect Reddit for real

- [ ] Log in: `POST /api/v1/auth/login` with your `onboard.py` email/password — keep the
      returned session cookie for every request below.
- [ ] `POST /api/v1/projects/{project_id}/plugin-connections` with
      `docs/examples/reddit-plugin-connection.json` as the body (edit `subreddits` first).
- [ ] `POST /api/v1/projects/{project_id}/plugin-connections/reddit/oauth/start` — open the
      returned `authorize_url` in a browser, log in as the Reddit account you're connecting,
      approve.
- [ ] `python scripts/status.py` shows the Reddit connection as `status=connected`.

## Configure the agents

- [ ] `PUT /api/v1/projects/{project_id}/agent-configs/conversation_finder` with
      `docs/examples/conversation-finder-config.json` (edit `keywords` first — search terms
      describing the problem you solve, not your product name).
- [ ] `PUT /api/v1/projects/{project_id}/agent-configs/content_agent` with
      `docs/examples/content-agent-config.json`.

## Run the first cycle, by hand — don't wait for a schedule yet

- [ ] `POST /api/v1/projects/{project_id}/agent-configs/conversation_finder/runs/trigger`
- [ ] `python scripts/status.py` — wait for the run to show `succeeded` (a few seconds; it's
      making real search calls to Reddit).
- [ ] `GET /api/v1/projects/{project_id}/knowledge-items` — confirm at least one real Reddit
      thread was discovered. If zero, your `keywords` may be too narrow or your connected
      subreddits too quiet — see `docs/beta/TROUBLESHOOTING_GUIDE.md`.
- [ ] Within a few seconds (event dispatch runs every 5s), Content Agent reacts automatically
      — no manual trigger needed. `python scripts/status.py` should show a `content_items`
      count increase.
- [ ] `GET /api/v1/projects/{project_id}/content-items?status=pending_review` — read the
      drafted reply. Check `confidence`, `reasoning`, and `evidence` — this is the agent's
      own self-assessment, not a guarantee it's good; read the actual `body` text yourself.

## Approve and publish your first real draft

- [ ] **Read the draft in full before approving it.** This is a real post to a real
      subreddit under a real account — there is no undo.
- [ ] `POST /api/v1/projects/{project_id}/content-items/{item_id}/approve` with
      `{"version": <the item's current version>}`.
- [ ] Within a few seconds, `python scripts/status.py` shows the item as `published`
      (or, if something went wrong, `approved` with a `publish_error` — see
      `docs/beta/TROUBLESHOOTING_GUIDE.md`).
- [ ] Check the actual subreddit — your reply should be live.

**You've now exercised the entire discover → draft → approve → publish loop against real
accounts.** See `docs/beta/BETA_TEST_PLAN.md` for how to run this on an ongoing basis
responsibly, and `docs/beta/KNOWN_LIMITATIONS.md` for what to watch out for.
