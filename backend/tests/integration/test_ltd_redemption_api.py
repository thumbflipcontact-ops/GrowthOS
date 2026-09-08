"""End-to-end tests for POST /ltd/redeem — see app/services/ltd_redemption_service.py and
app/api/v1/ltd.py.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.models.ltd_code import LtdCode, LtdCodeStatus
from app.repositories.organization_repository import OrganizationRepository

pytestmark = pytest.mark.integration


class _FakeArqRedis:
    async def ping(self) -> bool:
        return True


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
        frontend_origin="https://app.test",
    )


@pytest_asyncio.fixture
async def api_client(db_session, _migrated_db):
    from app.api.deps import get_arq_redis, get_db, get_ltd_redeem_ip_limiter, get_settings_dep
    from app.main import app

    async def override_get_db():
        yield db_session

    async def override_get_arq_redis():
        return _FakeArqRedis()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_arq_redis] = override_get_arq_redis
    app.dependency_overrides[get_settings_dep] = lambda: _settings()
    # The real limiter is a process-wide singleton (capacity=5), shared across every test in
    # the session — generous test-only instance here, same as every other rate-limited auth
    # endpoint's own test file does.
    app.dependency_overrides[get_ltd_redeem_ip_limiter] = lambda: RateLimiter(
        capacity=1000, refill_rate=1000
    )
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


async def _make_code(
    db_session, *, status: LtdCodeStatus = LtdCodeStatus.UNREDEEMED, source: str | None = None
) -> str:
    code = f"TEST-{uuid.uuid4().hex[:8].upper()}"
    db_session.add(LtdCode(code=code, status=status, source=source))
    await db_session.flush()
    return code


def _redeem_body(code: str, *, suffix: str = "1") -> dict:
    return {
        "code": code,
        "org_name": "Acme",
        "org_slug": f"acme-ltd-{suffix}",
        "email": f"ltd-buyer-{suffix}@example.com",
        "name": "Buyer",
        "password": "a-valid-password-123",
    }


@pytest.mark.asyncio
async def test_redeem_creates_an_ltd_org_with_one_project_allowed(
    api_client: AsyncClient, db_session
) -> None:
    code = await _make_code(db_session)

    r = await api_client.post("/api/v1/ltd/redeem", json=_redeem_body(code))
    assert r.status_code == 201
    assert r.json()["email"] == "ltd-buyer-1@example.com"

    org = await OrganizationRepository(db_session).get_by_slug("acme-ltd-1")
    assert org is not None
    assert org.is_ltd is True
    assert org.max_projects == 1

    updated_code = (
        await db_session.execute(select(LtdCode).where(LtdCode.code == code))
    ).scalar_one()
    assert updated_code.status == LtdCodeStatus.REDEEMED
    assert updated_code.redeemed_by_org_id == org.id
    assert updated_code.redeemed_at is not None


@pytest.mark.asyncio
async def test_redeem_preserves_the_codes_marketplace_source(
    api_client: AsyncClient, db_session
) -> None:
    """`source` (which marketplace batch this code came from — see
    scripts/generate_ltd_codes.py --source) is purely for redemption-count reporting;
    redeeming a code must never clear or overwrite it."""
    code = await _make_code(db_session, source="dealmirror")

    r = await api_client.post("/api/v1/ltd/redeem", json=_redeem_body(code))
    assert r.status_code == 201

    updated_code = (
        await db_session.execute(select(LtdCode).where(LtdCode.code == code))
    ).scalar_one()
    assert updated_code.source == "dealmirror"
    assert updated_code.status == LtdCodeStatus.REDEEMED


@pytest.mark.asyncio
async def test_redeem_with_an_unknown_code_fails(api_client: AsyncClient) -> None:
    r = await api_client.post("/api/v1/ltd/redeem", json=_redeem_body("NOT-A-REAL-CODE"))
    assert r.status_code == 422
    assert "invalid or has already been redeemed" in r.json()["error"]["message"]


@pytest.mark.asyncio
async def test_redeem_with_an_already_redeemed_code_fails(
    api_client: AsyncClient, db_session
) -> None:
    code = await _make_code(db_session, status=LtdCodeStatus.REDEEMED)

    r = await api_client.post("/api/v1/ltd/redeem", json=_redeem_body(code))
    assert r.status_code == 422
    assert "invalid or has already been redeemed" in r.json()["error"]["message"]


@pytest.mark.asyncio
async def test_redeeming_the_same_code_twice_only_succeeds_once(
    api_client: AsyncClient, db_session
) -> None:
    code = await _make_code(db_session)

    first = await api_client.post("/api/v1/ltd/redeem", json=_redeem_body(code, suffix="first"))
    assert first.status_code == 201

    second = await api_client.post(
        "/api/v1/ltd/redeem", json=_redeem_body(code, suffix="second")
    )
    assert second.status_code == 422


@pytest.mark.asyncio
async def test_redeem_sends_a_verification_email(
    api_client: AsyncClient, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.deps import get_settings_dep
    from app.main import app

    settings_with_resend = Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
        frontend_origin="https://app.test",
        resend_api_key="re_test_key",
        resend_from_email="Threadly <notifications@usethreadly.co>",
    )
    app.dependency_overrides[get_settings_dep] = lambda: settings_with_resend

    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"id": "email_123"})

    import app.core.email.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)

    code = await _make_code(db_session)
    r = await api_client.post("/api/v1/ltd/redeem", json=_redeem_body(code, suffix="verify"))
    assert r.status_code == 201
    assert len(sent) == 1
