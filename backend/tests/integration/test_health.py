"""Dedicated tests for GET /health — see docs/reviews/PRODUCTION_READINESS_REVIEW.md O1 and
docs/reviews/PRODUCTION_HARDENING_REPORT.md. The happy path (both checks "ok") is already
covered by test_api.py's test_health; this file is specifically the regression test proving
the endpoint no longer reports healthy through an outage.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


class _UnreachableRedis:
    async def ping(self) -> bool:
        raise ConnectionError("simulated: redis is unreachable")


@pytest_asyncio.fixture
async def api_client_with_unreachable_redis(db_session, _migrated_db):
    from app.api.deps import get_arq_redis, get_db
    from app.main import app

    async def override_get_db():
        yield db_session

    async def override_get_arq_redis():
        return _UnreachableRedis()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_arq_redis] = override_get_arq_redis
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_reports_503_when_redis_is_unreachable(
    api_client_with_unreachable_redis: AsyncClient,
) -> None:
    r = await api_client_with_unreachable_redis.get("/api/v1/health")

    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "ok"  # the real, working pgserver-backed engine
    assert "ConnectionError" in body["checks"]["redis"]
