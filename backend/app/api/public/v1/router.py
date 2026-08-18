"""The public, API-key-authed surface external tools (starting with the n8n community node)
call — see app/api/deps.py's require_api_key_project. Deliberately a top-level router
(prefix `/public/v1`, registered directly in app/main.py as a sibling of the cookie-authed
`api_router`), not nested under `/api/v1` — keeps this external contract visibly distinct from
the dashboard API, which docs/api/API_DESIGN.md says can evolve freely since it has one
consumer today. A ClawHub skill for OpenClaw agents is another consumer of this same surface.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.public.v1 import content, webhooks

public_api_router = APIRouter(prefix="/public/v1")
public_api_router.include_router(content.router)
public_api_router.include_router(webhooks.router)
