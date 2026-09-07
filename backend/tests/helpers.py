"""Shared test helpers. See docs/testing/TESTING.md.

register_and_login exists because /auth/register no longer grants a session by itself (see
app/services/email_verification_service.py) — most existing test fixtures register a user
purely as setup and expect the client to already be logged in afterward.
"""

from __future__ import annotations

from datetime import UTC, datetime

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession


async def register_and_login(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    org_name: str,
    org_slug: str,
    email: str,
    name: str,
    password: str,
) -> Response:
    """Registers via the real HTTP endpoint (so registration itself is still genuinely
    exercised), marks the account verified directly — skipping the real email round-trip, the
    same shortcut test_password_reset_api.py already takes for its own token — then logs in
    for real to obtain the session cookie /auth/register no longer grants on its own. Returns
    the original register response so callers asserting on its body/status don't need to
    change."""
    from app.repositories.user_repository import UserRepository

    register_response = await client.post(
        "/api/v1/auth/register",
        json={
            "org_name": org_name,
            "org_slug": org_slug,
            "email": email,
            "name": name,
            "password": password,
        },
    )
    if register_response.status_code != 201:
        return register_response  # let the caller assert on a legitimate registration failure

    user = await UserRepository(db_session).get_by_email(email)
    assert user is not None
    user.email_verified_at = datetime.now(UTC)
    await db_session.flush()

    login_response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login_response.status_code == 200, login_response.text
    return register_response
