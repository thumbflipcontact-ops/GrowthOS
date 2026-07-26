"""Health check — see docs/deployment/DEPLOYMENT.md "Observability in production" and
docs/reviews/PRODUCTION_READINESS_REVIEW.md O1.

Previously an unconditional `{"status": "ok"}` regardless of whether the database or Redis
were actually reachable — any orchestrator/monitor wired to this endpoint would report
healthy through a real outage. Now verifies the two dependencies that make the app
functional at all and returns 503 if either is unreachable.
"""

from __future__ import annotations

from arq import ArqRedis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.deps import get_arq_redis

router = APIRouter(tags=["health"])


async def _check_database(engine: AsyncEngine) -> str | None:
    """Returns None if reachable, else a short error description."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        return f"{exc.__class__.__name__}: {exc}"
    return None


async def _check_redis(arq_redis: ArqRedis) -> str | None:
    try:
        await arq_redis.ping()
    except Exception as exc:
        return f"{exc.__class__.__name__}: {exc}"
    return None


@router.get("/health")
async def health(
    request: Request,
    arq_redis: ArqRedis = Depends(get_arq_redis),
) -> JSONResponse:
    db_error = await _check_database(request.app.state.engine)
    redis_error = await _check_redis(arq_redis)
    healthy = db_error is None and redis_error is None

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "checks": {
                "database": "ok" if db_error is None else db_error,
                "redis": "ok" if redis_error is None else redis_error,
            },
        },
    )
