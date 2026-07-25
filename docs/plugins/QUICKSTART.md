# Plugin Quickstart

A linear, runnable walkthrough for building a new GrowthOS plugin, start to finish. This is
deliberately different from `docs/plugins/PLUGIN_ARCHITECTURE.md`, which explains *why* the
plugin system is shaped the way it is (manifest, segmented capability Protocols, the
registry's two gates). Read that first if you want the design rationale; come here when you
just want to get a plugin running.

Assumes you've already run `python scripts/setup.py` once (see `scripts/README.md`) — this
walkthrough uses the resulting `backend/.venv`.

## 1. Scaffold the package

```bash
python scripts/new_plugin.py my_plugin --capabilities searchable
```

This creates `plugins/my_plugin/` with a manifest, a `plugin.py` whose methods all raise
`NotImplementedError`, a `pyproject.toml` with the entry-point and packaging metadata already
correct (see §4 for why that metadata looks the way it does), a `README.md`, and
`tests/test_contract.py`. Pass `--capabilities searchable,publishable` (comma-separated, any
of `searchable`, `publishable`, `webhook_receivable`, `metrics_queryable`) and
`--auth-type oauth2|api_key|session_credentials` for anything other than the defaults.

## 2. Install it editable

```bash
uv pip install -e plugins/my_plugin --python backend/.venv
```

This registers `my_plugin`'s `growthos.plugins` entry point into `backend/.venv`, exactly
like installing any other Python package — nothing GrowthOS-specific here, no separate
"plugin registration" step to remember.

## 3. Confirm it's discovered

Run from the repo root, with both `backend/` (for `app`) and the repo root (for
`plugins._shared`) on `PYTHONPATH` — `app/core/plugin_catalog.py` needs both:

```bash
PYTHONPATH="backend;." backend/.venv/Scripts/python -c "from app.core.plugin_catalog import discover_installed_plugins; print([m.key for m in discover_installed_plugins()])"   # Windows (Git Bash)
PYTHONPATH="backend:." backend/.venv/bin/python -c "from app.core.plugin_catalog import discover_installed_plugins; print([m.key for m in discover_installed_plugins()])"         # macOS/Linux
```

(Running the actual app — `uvicorn app.main:app`, from `backend/` — doesn't need this; it
only matters for one-off scripts like this check. See `backend/pyproject.toml`'s
`pythonpath` note for why pytest doesn't need it either.)

`my_plugin` should be in the printed list. If it isn't: the most common cause is step 2 not
having actually run against `backend/.venv` (check `uv pip list --python backend/.venv | grep
growthos-plugin`), or a typo in `plugins/my_plugin/pyproject.toml`'s
`[project.entry-points."growthos.plugins"]` table.

## 4. Understand what you're about to edit

Two files, both already scaffolded:

- **`manifest.py`** — declares what your plugin is: its `key`, `capabilities`, and a pydantic
  `config_schema` for whatever a project needs to configure to connect it (a subreddit list,
  an API key, whatever). This is pure data — no network calls, no heavyweight imports.
- **`plugin.py`** — implements the capabilities your manifest declares. Every generated
  method currently raises `NotImplementedError`; replace each with real behavior against the
  actual external API.

`pyproject.toml`'s `package-dir = {"plugins.my_plugin" = "."}` line is the one genuinely
unusual bit: it tells setuptools that this distribution's `plugins.my_plugin` package is
rooted at the plugin's own directory, not a nested `src/` layout — needed because
`plugins/my_plugin/` sits inside the monorepo but installs as its own distribution. You don't
need to understand this to use it; `new_plugin.py` already generated it correctly. See
`docs/plugins/PLUGIN_ARCHITECTURE.md` §Discovery for the full reasoning.

## 5. Run your plugin's own tests

```bash
backend/.venv/Scripts/python -m pytest plugins/my_plugin/tests -p no:cov   # Windows, from repo root
backend/.venv/bin/python -m pytest plugins/my_plugin/tests -p no:cov       # macOS/Linux
```

The generated `tests/test_contract.py` calls
`plugins._shared.tests.test_plugin_contract.assert_plugin_contract` — the shared contract
suite every plugin should run (`CONTRIBUTING.md` "Adding a new plugin" step 5). Right now it
fails, because `health_check()` still raises `NotImplementedError`; that's expected until you
implement it. `assert_plugin_contract` only checks that your plugin structurally honors its
own manifest (every declared capability's methods actually exist, `health_check()` returns a
`bool`) — it does not and cannot verify your `search()`/`publish()`/etc. actually work against
the real external API. Add your own tests for that, in the same `tests/` folder, mocking or
recording the external API rather than making live calls from the test suite.

Lint and type-check your plugin directly (`scripts/lint.py` only covers `backend/`, since
`agents/` and `plugins/` are siblings of `backend/`, not under it):

```bash
backend/.venv/Scripts/ruff.exe check --config backend/pyproject.toml plugins/my_plugin
backend/.venv/Scripts/mypy.exe --config-file backend/pyproject.toml plugins/my_plugin
```

## 6. Rate limiting

If your plugin calls an external API with its own rate limit, use the shared limiter rather
than hand-rolling one:

```python
from plugins._shared.rate_limit import RateLimiter

limiter = RateLimiter(capacity=60, refill_rate=1.0)

if not limiter.try_acquire(plugin_key="my_plugin", project_id=str(project_id)):
    logger.warning("my_plugin.rate_limited", project_id=project_id)
    return []  # fewer/no results — never raise for a self-inflicted rate limit
```

See `docs/plugins/PLUGIN_ARCHITECTURE.md` §"Rate limiting & backoff" for the full contract,
including the known process-local limitation.

## 7. Connect it to a project

Once your plugin does something real, connect it to a project via the API (this is what the
frontend's generic connection form submits to):

```bash
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/plugin-connections \
  -H "Content-Type: application/json" \
  --cookie "growthos_session=<your session cookie>" \
  -d '{"plugin_key": "my_plugin", "config": {...matches your config_schema...}, "capabilities_enabled": ["searchable"]}'
```

The request is rejected (422) if `config` doesn't validate against your manifest's
`config_schema`, or if `capabilities_enabled` names something your manifest doesn't declare.
See `app/services/plugin_connection.py`. This request is not where credentials go, for any
`auth_type` — see step 8 for `oauth2`; `api_key`/`session_credentials` still have no
credential-setting flow built (Phase 2+ scope).

## 8. Connect an OAuth2 plugin

If your manifest declares `auth_type="oauth2"`, credentials are wired in through a real
authorize/callback flow instead of a request body — see `docs/auth/OAUTH2_ARCHITECTURE.md`
for the full design. First, register your plugin's OAuth app with its provider and set its
client credentials (see `docs/config/CONFIGURATION.md`):

```bash
# .env — {PLUGIN_KEY}_OAUTH_CLIENT_ID / _CLIENT_SECRET, uppercased
MY_PLUGIN_OAUTH_CLIENT_ID=...
MY_PLUGIN_OAUTH_CLIENT_SECRET=...
```

Then, authenticated as a GrowthOS user (a real browser session, not `curl` — the callback
needs the session cookie to carry through the provider's redirect):

```bash
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/plugin-connections/my_plugin/oauth/start \
  --cookie "growthos_session=<your session cookie>"
# → {"authorize_url": "https://provider.example/oauth/authorize?..."}
```

Navigate a browser to `authorize_url`. After you approve, the provider redirects to
`GET /api/v1/oauth/my_plugin/callback`, which exchanges the code, envelope-encrypts the
resulting tokens (ADR 0010 — the exact same mechanism any other plugin credential uses), and
redirects the browser to `Settings.oauth_frontend_redirect_url` with `?connected=my_plugin`
(or `?error=...` on failure). Your plugin's `create_plugin()` then receives real
`OAuth2Credentials` — see `docs/plugins/PLUGIN_ARCHITECTURE.md` §Credentials.

Nothing about token refresh is your plugin's concern — a background job
(`app/jobs/oauth_refresh.py`) keeps connected tokens current automatically.

## What this quickstart deliberately does not cover

- **Webhook ingress** (`WebhookReceivable`) — the SDK contract (`handle_webhook(payload, *,
  events: DomainEventPublisher)`) is real and testable (see
  `docs/plugins/PLUGIN_ARCHITECTURE.md` §"Webhooks and events"), but the `POST
  /webhooks/{plugin_key}` route that would actually call it doesn't exist yet.
- **Publishing through the approval flow** — `publish()` is only ever called by the publish
  worker on an already-`approved` `ContentItem`; that worker's real body is Phase 2+ business
  logic, not part of the plugin platform itself.
- **`api_key`/`session_credentials` credential-setting** — no request path writes
  `credentials_encrypted` for these auth types yet; only the `oauth2` flow (step 8) is built.
