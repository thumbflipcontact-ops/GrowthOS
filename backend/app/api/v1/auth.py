"""Auth endpoints — the "Authentication scaffold" foundation piece.
See docs/auth/AUTHENTICATION.md.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_settings_dep
from app.core.config import Settings
from app.core.security import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_session_token,
    generate_csrf_token,
)
from app.models.identity import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(response: Response, user_id: str, settings: Settings) -> None:
    is_secure = not settings.is_local
    session_token = create_session_token(
        uuid.UUID(user_id), secret_key=settings.secret_key.get_secret_value()
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=is_secure,
        samesite="lax",
    )
    # CSRF cookie is intentionally NOT httponly — the frontend reads it and echoes it back
    # in a request header on state-changing requests (double-submit pattern), see
    # docs/auth/AUTHENTICATION.md.
    response.set_cookie(
        CSRF_COOKIE_NAME,
        generate_csrf_token(),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=False,
        secure=is_secure,
        samesite="lax",
    )


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: RegisterRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> User:
    service = AuthService(session)
    user = await service.register(
        org_name=body.org_name,
        org_slug=body.org_slug,
        email=body.email,
        name=body.name,
        password=body.password,
    )
    _set_session_cookies(response, str(user.id), settings)
    return user


@router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> User:
    service = AuthService(session)
    user = await service.authenticate(email=body.email, password=body.password)
    _set_session_cookies(response, str(user.id), settings)
    return user


@router.post("/logout", status_code=204, response_model=None)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie(CSRF_COOKIE_NAME)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
