"""Health check — see docs/deployment/DEPLOYMENT.md "Observability in production"."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
