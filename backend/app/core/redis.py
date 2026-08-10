"""Shared arq `RedisSettings` construction — the one place every worker/scheduler/API process
builds its Redis connection config, so a fix here (like this module's own reason for existing)
applies everywhere at once instead of needing six separate edits.

arq's own `RedisSettings` defaults are too aggressive for a real deployment: `conn_timeout=1`
(second) and `retry_on_timeout=False`. Over Railway's internal network, a single GC pause or
brief network blip easily exceeds 1 second, and since retry-on-timeout is off, that one blip
raises `redis.exceptions.TimeoutError` straight out of arq's job-processing loop — unhandled,
which crashes the entire worker process (confirmed via Sentry: PYTHON-FASTAPI-3, "TimeoutError:
Timeout connecting to server", seen across worker-events and worker-oauth-refresh within the
same hour). Railway's restart policy makes this self-healing, but a full process crash on a
transient blip is still worse than the operation just retrying.
"""

from __future__ import annotations

from arq.connections import RedisSettings

from app.core.config import Settings

# arq's own conn_retries=5 already retries pool *creation* at startup; retry_on_timeout=True
# additionally makes each individual redis-py operation retry once after a timeout instead of
# raising immediately. 5 seconds (vs arq's 1-second default) gives a real network hiccup room
# to clear without needlessly extending genuine outage detection.
_CONN_TIMEOUT_SECONDS = 5


def build_redis_settings(settings: Settings) -> RedisSettings:
    redis_settings = RedisSettings.from_dsn(str(settings.redis_url))
    redis_settings.conn_timeout = _CONN_TIMEOUT_SECONDS
    redis_settings.retry_on_timeout = True
    return redis_settings
