#!/usr/bin/env python3
"""Environment doctor — validates that GrowthOS is correctly configured and its real
dependencies (Postgres, Redis) are reachable, before you try to run it for real. See
docs/beta/TROUBLESHOOTING_GUIDE.md and docs/beta/FIRST_RUN_CHECKLIST.md.

Run: python scripts/check_env.py
Exit code 0 if every check passes (warnings don't fail the run), 1 otherwise.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))

# Values that only ever belong in tests (see backend/tests/conftest.py) — a real deployment
# using one of these means someone copy-pasted the test environment instead of setting a real
# secret, which is a genuine security problem (this string is public, it's in this file).
_KNOWN_TEST_SECRETS = {
    "test-secret-key-not-for-production-use",
    "test-master-key-not-for-production-use",
}


@dataclass
class CheckResult:
    name: str
    status: str  # "ok" | "warn" | "fail"
    detail: str
    hint: str | None = None


async def _check_settings(results: list[CheckResult]) -> object | None:
    try:
        from app.core.config import get_settings

        settings = get_settings()
    except Exception as exc:
        results.append(
            CheckResult(
                "Settings",
                "fail",
                f"{exc.__class__.__name__}: {exc}",
                "Copy .env.example to .env and fill in real values - see "
                "docs/config/CONFIGURATION.md and docs/beta/SETUP_GUIDE.md.",
            )
        )
        return None

    results.append(CheckResult("Settings", "ok", "all required environment variables are set"))
    return settings


def _check_secret_strength(results: list[CheckResult], settings: object) -> None:
    for field_name, label in (("secret_key", "SECRET_KEY"), ("credential_master_key", "CREDENTIAL_MASTER_KEY")):
        value = getattr(settings, field_name).get_secret_value()
        if value in _KNOWN_TEST_SECRETS:
            results.append(
                CheckResult(
                    label,
                    "fail",
                    "set to the test-suite's known placeholder value",
                    f"Generate a real random value for {label} - never reuse the test value "
                    "outside `backend/tests/`. E.g. `python -c \"import secrets; "
                    'print(secrets.token_urlsafe(32))"`.',
                )
            )
        elif len(value) < 16:
            results.append(
                CheckResult(
                    label,
                    "warn",
                    f"only {len(value)} characters - unusually short for a signing/encryption key",
                    f"Consider a longer, higher-entropy value for {label}.",
                )
            )
        else:
            results.append(CheckResult(label, "ok", "set, not a known test placeholder"))


async def _check_database(results: list[CheckResult], settings: object) -> object | None:
    try:
        from sqlalchemy import text

        from app.core.db import create_engine

        engine = create_engine(
            str(settings.database_url),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        results.append(
            CheckResult(
                "Database",
                "fail",
                f"{exc.__class__.__name__}: {exc}",
                "Is Postgres running and DATABASE_URL correct? For a Docker-free local "
                "instance: `cd backend && .venv/Scripts/python scripts/dev_postgres.py` "
                "(Windows) or `.venv/bin/python scripts/dev_postgres.py` (macOS/Linux).",
            )
        )
        return None

    # PostgresDsn is a MultiHostUrl (supports HA host lists) — .host/.port aren't attributes
    # on it directly, unlike RedisDsn below.
    host_info = settings.database_url.hosts()[0]  # type: ignore[attr-defined]
    results.append(
        CheckResult("Database", "ok", f"connected to {host_info['host']}:{host_info['port']}")
    )
    return engine


async def _check_migrations(results: list[CheckResult], engine: object) -> None:
    try:
        from app.core.migration_check import DatabaseNotMigrated, verify_database_is_migrated

        await verify_database_is_migrated(engine)  # type: ignore[arg-type]
    except DatabaseNotMigrated as exc:
        results.append(
            CheckResult("Migrations", "fail", str(exc), "Run `python scripts/migrate.py`.")
        )
        return
    except Exception as exc:
        results.append(CheckResult("Migrations", "fail", f"{exc.__class__.__name__}: {exc}"))
        return

    results.append(CheckResult("Migrations", "ok", "database is at the expected Alembic revision"))


async def _check_redis(results: list[CheckResult], settings: object) -> None:
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        # arq's own default retries a failed connection 5 times with a 1s delay between —
        # fine for a long-running worker process, but this is a one-shot diagnostic check
        # that should fail fast, not silently sit for ~5s before reporting the obvious.
        redis_settings = RedisSettings.from_dsn(str(settings.redis_url))
        redis_settings.conn_retries = 0
        pool = await create_pool(redis_settings)
        await pool.ping()
        await pool.aclose()
    except Exception as exc:
        results.append(
            CheckResult(
                "Redis",
                "fail",
                f"{exc.__class__.__name__}: {exc}",
                "Is Redis running and REDIS_URL correct? A local `redis-server` (no Docker "
                "required) or `docker compose up redis` both work.",
            )
        )
        return

    results.append(
        CheckResult("Redis", "ok", f"connected to {settings.redis_url.host}:{settings.redis_url.port}")
    )


def _check_plugin_catalog(results: list[CheckResult]) -> None:
    try:
        from app.core.plugin_catalog import PluginCatalog, discover_installed_plugins

        catalog = PluginCatalog()
        catalog.refresh(discover_installed_plugins())
        keys = sorted(m.key for m in catalog.all())
    except Exception as exc:
        results.append(CheckResult("Plugin catalog", "fail", f"{exc.__class__.__name__}: {exc}"))
        return

    if not keys:
        results.append(
            CheckResult(
                "Plugin catalog",
                "fail",
                "no plugins discovered",
                "Expected at least `reddit` and `dummy` - was `pip install -e plugins/reddit "
                "--python backend/.venv` (and similarly for agents/*) run? See "
                "docs/beta/SETUP_GUIDE.md.",
            )
        )
    else:
        results.append(CheckResult("Plugin catalog", "ok", f"discovered: {', '.join(keys)}"))


def _check_reddit_oauth_credentials(results: list[CheckResult]) -> None:
    client_id = os.environ.get("REDDIT_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_OAUTH_CLIENT_SECRET")
    if client_id and client_secret:
        results.append(CheckResult("Reddit OAuth credentials", "ok", "REDDIT_OAUTH_CLIENT_ID/SECRET are set"))
    else:
        results.append(
            CheckResult(
                "Reddit OAuth credentials",
                "warn",
                "REDDIT_OAUTH_CLIENT_ID/SECRET not set",
                "Not required until you actually connect a Reddit account - see "
                "docs/beta/SETUP_GUIDE.md's Reddit app registration steps.",
            )
        )


def _check_polar_billing_credentials(results: list[CheckResult], settings: object) -> None:
    access_token = getattr(settings, "polar_access_token", None)
    webhook_secret = getattr(settings, "polar_webhook_secret", None)
    product_id = getattr(settings, "polar_product_id", None)
    if access_token and webhook_secret and product_id:
        server = getattr(settings, "polar_server", "sandbox")
        results.append(
            CheckResult(
                "Polar billing credentials", "ok", f"POLAR_* are set (server={server})"
            )
        )
    else:
        results.append(
            CheckResult(
                "Polar billing credentials",
                "warn",
                "POLAR_ACCESS_TOKEN/POLAR_WEBHOOK_SECRET/POLAR_PRODUCT_ID not fully set",
                "Not required until you actually accept a paid signup - see "
                "docs/billing/BILLING_ARCHITECTURE.md's Setup section.",
            )
        )


def _check_resend_credentials(results: list[CheckResult], settings: object) -> None:
    api_key = getattr(settings, "resend_api_key", None)
    from_email = getattr(settings, "resend_from_email", None)
    if api_key and from_email:
        results.append(CheckResult("Resend email credentials", "ok", "RESEND_* are set"))
    else:
        results.append(
            CheckResult(
                "Resend email credentials",
                "warn",
                "RESEND_API_KEY/RESEND_FROM_EMAIL not fully set",
                "Not required until app/core/agent_lifecycle.py's sweep actually needs to "
                "notify someone - see .env.example's Resend section.",
            )
        )


def _check_anthropic_key(results: list[CheckResult], settings: object) -> None:
    value = settings.anthropic_api_key.get_secret_value()  # type: ignore[attr-defined]
    if not value or value in ("x", "test-anthropic-key") or value.startswith("test-"):
        results.append(
            CheckResult(
                "Anthropic API key",
                "warn",
                "looks like a placeholder, not a real key",
                "Content Agent will fail to draft anything until a real "
                "ANTHROPIC_API_KEY is set. Run with --live-llm-check to actually verify it.",
            )
        )
    else:
        results.append(CheckResult("Anthropic API key", "ok", "set (format looks like a real key)"))


async def _check_anthropic_live(results: list[CheckResult], settings: object) -> None:
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())  # type: ignore[attr-defined]
        await client.messages.create(
            model=settings.anthropic_model,  # type: ignore[attr-defined]
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
    except Exception as exc:
        results.append(
            CheckResult(
                "Anthropic API (live check)",
                "fail",
                f"{exc.__class__.__name__}: {exc}",
                "Verify the key at https://console.anthropic.com/settings/keys and that "
                "billing is set up.",
            )
        )
        return
    results.append(CheckResult("Anthropic API (live check)", "ok", "a real completion request succeeded"))


def _print_report(results: list[CheckResult]) -> int:
    icons = {"ok": "[OK]  ", "warn": "[WARN]", "fail": "[FAIL]"}
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"{icons[r.status]} {r.name.ljust(width)}  {r.detail}")
        if r.hint and r.status != "ok":
            print(f"         -> {r.hint}")

    failed = [r for r in results if r.status == "fail"]
    warned = [r for r in results if r.status == "warn"]
    print()
    if not failed and not warned:
        print("All checks passed. GrowthOS is ready to run.")
    elif not failed:
        print(f"{len(warned)} warning(s), 0 failures - safe to proceed, but review the warnings above.")
    else:
        print(f"{len(failed)} check(s) failed, {len(warned)} warning(s) - fix the failures above before continuing.")
    return 1 if failed else 0


async def main() -> int:
    live = "--live-llm-check" in sys.argv
    results: list[CheckResult] = []

    settings = await _check_settings(results)
    if settings is None:
        return _print_report(results)

    _check_secret_strength(results, settings)

    engine = await _check_database(results, settings)
    if engine is not None:
        await _check_migrations(results, engine)
        await engine.dispose()  # type: ignore[attr-defined]

    await _check_redis(results, settings)
    _check_plugin_catalog(results)
    _check_reddit_oauth_credentials(results)
    _check_polar_billing_credentials(results, settings)
    _check_resend_credentials(results, settings)
    _check_anthropic_key(results, settings)
    if live:
        await _check_anthropic_live(results, settings)

    return _print_report(results)


if __name__ == "__main__":
    from _bootstrap import ensure_running_under_backend_venv

    ensure_running_under_backend_venv(__file__)
    sys.exit(asyncio.run(main()))
