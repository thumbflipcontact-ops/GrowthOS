# Setup Guide

Everything needed to get GrowthOS running on your own machine with your own accounts, start
to finish. This is the narrative version of `docs/beta/FIRST_RUN_CHECKLIST.md` — read this
once, then use the checklist for the actual run-through.

## 1. Prerequisites

- Python 3.12 (not 3.13 — `pgserver`, the embedded-Postgres dependency used for local
  development, has no Python 3.13 Windows wheel yet).
- A real Postgres 16+ with the `pgvector` extension available, **or** use the bundled
  Docker-free embedded option in step 3 below (recommended for a first run).
- A real Redis instance (a local `redis-server`, or `docker compose up redis` if you have
  Docker — see `docker/README.md`).
- An [Anthropic API key](https://console.anthropic.com/settings/keys) (Content Agent won't
  draft anything without one — billed per use).
- A Reddit account you're comfortable posting from, and a few minutes to register a Reddit
  API app (step 6 below).

## 2. Clone and install

```bash
git clone <this repo>
cd GrowthOS
python scripts/setup.py
```

This installs `uv`, provisions a Python 3.12 virtualenv at `backend/.venv`, installs every
backend dependency, and copies `.env.example` to `.env`.

## 3. Start Postgres and Redis

**Docker-free (recommended for a first run)** — a real, embedded Postgres, no install needed:

```bash
cd backend
.venv/Scripts/python scripts/dev_postgres.py    # Windows
.venv/bin/python scripts/dev_postgres.py         # macOS/Linux
```

This prints a `DATABASE_URL` — copy it into your `.env` file (it changes every time you start
a fresh instance, since it binds to a random local port). Leave this process running in its
own terminal.

You still need a real Redis — either install one locally, or (only for Redis specifically,
not the whole stack) `docker compose up redis` from `docker/docker-compose.yml`.

**Or use Docker Compose for everything** — see `docs/deployment/DEPLOYMENT.md`. Untested
end-to-end as of this writing (see `docs/beta/KNOWN_LIMITATIONS.md`); the Docker-free path
above is what this project's own development actually uses.

## 4. Configure `.env`

Open `.env` (created in step 2) and fill in at minimum:

```bash
DATABASE_URL=...          # from step 3
REDIS_URL=redis://localhost:6379/0
ANTHROPIC_API_KEY=...     # your real key
OPENAI_API_KEY=x          # required to boot even though nothing implements it yet — any
                           # non-empty value works, see docs/config/CONFIGURATION.md
SECRET_KEY=...            # generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
CREDENTIAL_MASTER_KEY=... # generate the same way — a SEPARATE random value, not the same one
```

See `docs/config/CONFIGURATION.md` for every variable and what it's for.

**Verify it all actually works before going further:**

```bash
python scripts/check_env.py
```

This is the single most useful command in this guide — it tells you exactly what's wrong
(wrong DB, unreachable Redis, un-run migrations, placeholder secrets) instead of you
discovering it three steps later as a confusing stack trace. Fix everything it flags before
continuing; see `docs/beta/TROUBLESHOOTING_GUIDE.md` if a fix isn't obvious from the hint it
prints.

## 5. Run migrations and create your account

```bash
python scripts/migrate.py
python scripts/onboard.py
```

`onboard.py` walks you through creating your organization, your (real) login, and your first
project, then prints the exact next-step commands with your real project id filled in — save
that output, you'll need the project id repeatedly below.

## 6. Register a Reddit app and connect it

1. Go to <https://www.reddit.com/prefs/apps> → "create another app...".
2. Type: **script** (simplest for a single-operator setup) or **web app**.
3. Redirect URI: `{OAUTH_CALLBACK_BASE_URL}/api/v1/oauth/reddit/callback` — with the default
   local `.env`, that's `http://localhost:8000/api/v1/oauth/reddit/callback`.
4. Copy the generated client id and secret into `.env`:
   ```bash
   REDDIT_OAUTH_CLIENT_ID=...
   REDDIT_OAUTH_CLIENT_SECRET=...
   ```
5. Start the backend (see step 7), then create the connection and start the OAuth flow —
   `docs/examples/reddit-plugin-connection.json` is a ready-to-use request body:
   ```bash
   curl -X POST http://localhost:8000/api/v1/projects/{project_id}/plugin-connections \
     --cookie "growthos_session=<from logging in>" \
     -H "Content-Type: application/json" \
     -d @docs/examples/reddit-plugin-connection.json

   curl -X POST http://localhost:8000/api/v1/projects/{project_id}/plugin-connections/reddit/oauth/start \
     --cookie "growthos_session=<from logging in>"
   ```
   The response's `authorize_url` is a real Reddit URL — open it in a browser, log in as the
   Reddit account you want to post from, and approve access. You're redirected back and the
   connection is marked `connected` automatically; no further step needed.

## 7. Start the application

Five more processes, each in its own terminal (see `docs/deployment/DEPLOYMENT.md`'s
"Non-Docker deployment" for the exact commands and what each one does):

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000     # backend
python -m app.scheduler                              # scheduler
arq app.jobs.agent_runs.WorkerSettings                # worker-agents
arq app.jobs.events.WorkerSettings                      # worker-events
arq app.jobs.publish.WorkerSettings                       # worker-publish
arq app.jobs.oauth_refresh.WorkerSettings                  # worker-oauth-refresh
```

Confirm it's actually healthy: `curl http://localhost:8000/api/v1/health` should return
`{"status": "ok", ...}`. Check overall progress any time with `python scripts/status.py`.

## 8. Configure the agents and run your first cycle

See `docs/beta/FIRST_RUN_CHECKLIST.md` for the rest — configuring Conversation Finder and
Content Agent (`docs/examples/` has ready-to-use payloads), triggering a run, and reviewing
your first draft.
