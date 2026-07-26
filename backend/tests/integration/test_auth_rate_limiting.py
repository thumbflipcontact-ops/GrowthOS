"""Tests for POST /auth/login rate limiting — see docs/reviews/PRODUCTION_READINESS_REVIEW.md
S1 and docs/reviews/PRODUCTION_HARDENING_REPORT.md.

Each test overrides the login rate limiters with tiny, test-specific capacities via FastAPI's
dependency-override mechanism (app/api/deps.py's get_login_ip_limiter/
get_login_account_limiter) — never the production-sized defaults (10/5min, 5/15min), and never
the same singleton instance across tests, so this suite can trip the limit deterministically
without waiting on real time or leaking rate-limit state into unrelated tests elsewhere.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.rate_limit import RateLimiter

pytestmark = pytest.mark.integration


class _FakeArqRedis:
    async def ping(self) -> bool:
        return True


def _make_api_client_fixture(*, ip_capacity: int, account_capacity: int):
    @pytest_asyncio.fixture
    async def _fixture(db_session, _migrated_db):
        from app.api.deps import (
            get_arq_redis,
            get_db,
            get_login_account_limiter,
            get_login_ip_limiter,
        )
        from app.main import app

        ip_limiter = RateLimiter(capacity=ip_capacity, refill_rate=0.0001)
        account_limiter = RateLimiter(capacity=account_capacity, refill_rate=0.0001)

        async def override_get_db():
            yield db_session

        async def override_get_arq_redis():
            return _FakeArqRedis()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_arq_redis] = override_get_arq_redis
        app.dependency_overrides[get_login_ip_limiter] = lambda: ip_limiter
        app.dependency_overrides[get_login_account_limiter] = lambda: account_limiter
        try:
            async with app.router.lifespan_context(app):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    yield client
        finally:
            app.dependency_overrides.clear()

    return _fixture


# ip_capacity tiny, account_capacity generous — isolates the per-IP limiter.
api_client_tiny_ip_limit = _make_api_client_fixture(ip_capacity=2, account_capacity=1000)
# account_capacity tiny, ip_capacity generous — isolates the per-account limiter.
api_client_tiny_account_limit = _make_api_client_fixture(ip_capacity=1000, account_capacity=2)


@pytest.mark.asyncio
async def test_login_returns_429_once_the_per_ip_limit_is_exhausted(
    api_client_tiny_ip_limit: AsyncClient,
) -> None:
    # A different (nonexistent) email each call — isolates this test from the per-account
    # limiter, which is set to a generous capacity here anyway.
    for i in range(2):  # ip_capacity=2
        r = await api_client_tiny_ip_limit.post(
            "/api/v1/auth/login", json={"email": f"nobody-{i}@example.com", "password": "wrong"}
        )
        assert r.status_code == 401  # limiter allowed it through; account just doesn't exist

    r = await api_client_tiny_ip_limit.post(
        "/api/v1/auth/login", json={"email": "nobody-3@example.com", "password": "wrong"}
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_requests"


@pytest.mark.asyncio
async def test_login_returns_429_once_the_per_account_limit_is_exhausted(
    api_client_tiny_account_limit: AsyncClient,
) -> None:
    target_email = "target@example.com"
    for _ in range(2):  # account_capacity=2
        r = await api_client_tiny_account_limit.post(
            "/api/v1/auth/login", json={"email": target_email, "password": "wrong"}
        )
        assert r.status_code == 401

    r = await api_client_tiny_account_limit.post(
        "/api/v1/auth/login", json={"email": target_email, "password": "wrong"}
    )
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_a_rate_limited_account_does_not_affect_a_different_account(
    api_client_tiny_account_limit: AsyncClient,
) -> None:
    for _ in range(3):  # exhausts target@example.com's 2-token bucket (3rd call gets 429)
        await api_client_tiny_account_limit.post(
            "/api/v1/auth/login", json={"email": "target@example.com", "password": "wrong"}
        )

    r = await api_client_tiny_account_limit.post(
        "/api/v1/auth/login", json={"email": "someone-else@example.com", "password": "wrong"}
    )
    assert r.status_code == 401  # a different account's bucket is untouched — not 429
