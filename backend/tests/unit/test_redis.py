"""See app/core/redis.py — arq's own RedisSettings.from_dsn() defaults (conn_timeout=1,
retry_on_timeout=False) are too aggressive for Railway's internal network; build_redis_settings
overrides both. Covered here since every worker/scheduler/API call site now goes through it."""

from __future__ import annotations

from app.core.config import Settings
from app.core.redis import build_redis_settings

_SETTINGS = Settings(
    database_url="postgresql://x:x@localhost:5432/x",
    redis_url="redis://localhost:6379/0",
    anthropic_api_key="x",
    openai_api_key="x",
    secret_key="x",
    credential_master_key="x",
)


def test_build_redis_settings_overrides_arqs_aggressive_defaults() -> None:
    redis_settings = build_redis_settings(_SETTINGS)

    assert redis_settings.conn_timeout == 5
    assert redis_settings.retry_on_timeout is True


def test_build_redis_settings_still_parses_the_dsn() -> None:
    redis_settings = build_redis_settings(_SETTINGS)

    assert redis_settings.host == "localhost"
    assert redis_settings.port == 6379
    assert redis_settings.database == 0
