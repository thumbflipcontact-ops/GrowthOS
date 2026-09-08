"""AppSumo-style lifetime-deal code redemption endpoint — see
app/services/ltd_redemption_service.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_ltd_redeem_ip_limiter, get_settings_dep
from app.core.config import Settings
from app.core.errors import TooManyRequests
from app.core.rate_limit import RateLimiter
from app.models.identity import User
from app.schemas.auth import UserResponse
from app.schemas.ltd import RedeemLtdCodeRequest
from app.services.email_verification_service import EmailVerificationService
from app.services.ltd_redemption_service import LtdRedemptionService

router = APIRouter(prefix="/ltd", tags=["ltd"])


@router.post("/redeem", response_model=UserResponse, status_code=201)
async def redeem_ltd_code(
    body: RedeemLtdCodeRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    ip_limiter: RateLimiter = Depends(get_ltd_redeem_ip_limiter),
) -> User:
    client_ip = request.client.host if request.client else "unknown"
    if not ip_limiter.try_acquire(f"ip:{client_ip}"):
        raise TooManyRequests("Too many attempts from this address. Try again shortly.")

    service = LtdRedemptionService(session)
    user = await service.redeem(
        code=body.code,
        org_name=body.org_name,
        org_slug=body.org_slug,
        email=body.email,
        name=body.name,
        password=body.password,
    )
    # Same as /auth/register — no session cookie yet, withheld until /auth/verify-email
    # confirms this is a real, reachable address.
    await EmailVerificationService(session, settings).send_verification_email(user=user)
    return user
