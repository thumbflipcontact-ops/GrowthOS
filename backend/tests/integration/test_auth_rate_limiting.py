"""Tests for POST /auth/login and POST /auth/register rate limiting — see
docs/reviews/PRODUCTION_READINESS_REVIEW.md S1 and docs/reviews/PRODUCTION_HARDENING_REPORT.md.

Each test overrides the relevant rate limiter(s) with tiny, test-specific capacities via
FastAPI's dependency-override mechanism (app/api/deps.py's get_login_ip_limiter/
get_login_account_limiter/get_register_ip_limiter) — never the production-sized defaults, and
never the same singleton instance across tests, so this suite can trip the limit
deterministically without waiting on real time or leaking rate-limit state into unrelated
tests elsewhere.
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


@pytest_asyncio.fixture
async def api_client_tiny_register_limit(db_session, _migrated_db):
    from app.api.deps import get_arq_redis, get_db, get_register_ip_limiter
    from app.main import app

    ip_limiter = RateLimiter(capacity=2, refill_rate=0.0001)

    async def override_get_db():
        yield db_session

    async def override_get_arq_redis():
        return _FakeArqRedis()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_arq_redis] = override_get_arq_redis
    app.dependency_overrides[get_register_ip_limiter] = lambda: ip_limiter
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def api_client_tiny_global_register_limit(db_session, _migrated_db):
    # Mirrors api_client_tiny_register_limit above, but shrinks the system-wide backstop
    # limiter instead of the per-IP one — isolates get_register_global_limiter the same way
    # api_client_tiny_ip_limit isolates login's per-IP limiter from its per-account sibling.
    from app.api.deps import get_arq_redis, get_db, get_register_global_limiter
    from app.main import app

    global_limiter = RateLimiter(capacity=2, refill_rate=0.0001)

    async def override_get_db():
        yield db_session

    async def override_get_arq_redis():
        return _FakeArqRedis()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_arq_redis] = override_get_arq_redis
    app.dependency_overrides[get_register_global_limiter] = lambda: global_limiter
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


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


@pytest.mark.asyncio
async def test_register_returns_429_once_the_per_ip_limit_is_exhausted(
    api_client_tiny_register_limit: AsyncClient,
) -> None:
    # A different email/org each call — registration succeeding (not some other rejection) is
    # what proves the limiter, not the account layer, is what's isolated here.
    for i in range(2):  # ip_capacity=2
        r = await api_client_tiny_register_limit.post(
            "/api/v1/auth/register",
            json={
                "org_name": f"Org {i}",
                "org_slug": f"org-{i}",
                "email": f"signup-{i}@example.com",
                "name": "Test User",
                "password": "a-valid-password-123",
            },
        )
        assert r.status_code == 201

    r = await api_client_tiny_register_limit.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Org 3",
            "org_slug": "org-3",
            "email": "signup-3@example.com",
            "name": "Test User",
            "password": "a-valid-password-123",
        },
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_requests"


@pytest.mark.asyncio
async def test_x_forwarded_for_is_what_the_limiter_actually_keys_on(
    api_client_tiny_register_limit: AsyncClient,
) -> None:
    """Regression test for a real production bug: this service sits behind Railway's edge,
    which proxies every request through a different internal address — without trusting
    X-Forwarded-For (app/main.py's trust_forwarded_for middleware), every request looked like
    a different "IP" to the limiter and it silently never limited anything. Two distinct
    forwarded-for values must get independent buckets; the same value repeated must not."""

    def _register(i: int, forwarded_for: str) -> dict:
        return dict(
            json={
                "org_name": f"FwdOrg {i}",
                "org_slug": f"fwd-org-{i}",
                "email": f"fwd-signup-{i}@example.com",
                "name": "Test User",
                "password": "a-valid-password-123",
            },
            headers={"X-Forwarded-For": forwarded_for},
        )

    # Two calls from "1.1.1.1" exhaust its 2-token bucket (ip_capacity=2).
    for i in range(2):
        r = await api_client_tiny_register_limit.post(
            "/api/v1/auth/register", **_register(i, "1.1.1.1")
        )
        assert r.status_code == 201
    r = await api_client_tiny_register_limit.post(
        "/api/v1/auth/register", **_register(2, "1.1.1.1")
    )
    assert r.status_code == 429

    # A different forwarded-for value has its own untouched bucket.
    r = await api_client_tiny_register_limit.post(
        "/api/v1/auth/register", **_register(3, "2.2.2.2")
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_register_returns_429_once_the_global_limit_is_exhausted_across_different_ips(
    api_client_tiny_global_register_limit: AsyncClient,
) -> None:
    """The per-IP limiter alone can't stop a bot swarm spread across many addresses (see
    get_register_global_limiter's docstring) — this proves the system-wide bucket is shared
    across requests presenting entirely different X-Forwarded-For values, unlike the per-IP
    limiter above where a different value gets its own untouched bucket."""

    def _register(i: int, forwarded_for: str) -> dict:
        return dict(
            json={
                "org_name": f"GlobalOrg {i}",
                "org_slug": f"global-org-{i}",
                "email": f"global-signup-{i}@example.com",
                "name": "Test User",
                "password": "a-valid-password-123",
            },
            headers={"X-Forwarded-For": forwarded_for},
        )

    # Two calls from two DIFFERENT addresses still exhaust the one shared global bucket
    # (capacity=2) — a different per-IP bucket would let both of these through independently.
    for i in range(2):
        r = await api_client_tiny_global_register_limit.post(
            "/api/v1/auth/register", **_register(i, f"10.0.0.{i}")
        )
        assert r.status_code == 201

    r = await api_client_tiny_global_register_limit.post(
        "/api/v1/auth/register", **_register(2, "10.0.0.99")
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_requests"


@pytest.mark.asyncio
async def test_register_honeypot_field_fakes_success_without_creating_an_account(
    api_client_tiny_register_limit: AsyncClient,
) -> None:
    """A real user never sees or fills RegisterRequest.website (frontend/app/signup/page.tsx
    renders it visually hidden, out of tab order) — a scripted client that blindly fills every
    field it finds does. The response must still look like a real 201 success (so the bot has
    no signal to adapt on), but no organization/user row may actually exist afterward."""
    from sqlalchemy import select

    from app.models.identity import User

    r = await api_client_tiny_register_limit.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Bot Org",
            "org_slug": "bot-org",
            "email": "bot-honeypot@example.com",
            "name": "Bot",
            "password": "a-valid-password-123",
            "website": "https://spam.example.com",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "bot-honeypot@example.com"
    assert body["name"] == "Bot"

    # This test's db_session is shared with the app (see the fixture above's override_get_db),
    # so a direct query is the ground truth for whether register() actually persisted anything.
    from app.api.deps import get_db
    from app.main import app

    session_override = app.dependency_overrides[get_db]
    async for session in session_override():
        result = await session.execute(select(User).where(User.email == "bot-honeypot@example.com"))
        assert result.scalar_one_or_none() is None
        break
