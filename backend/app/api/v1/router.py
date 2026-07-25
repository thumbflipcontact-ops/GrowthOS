from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    agent_configs,
    auth,
    health,
    knowledge_items,
    oauth,
    plugin_connections,
    plugins,
    projects,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(plugins.router)
api_router.include_router(plugin_connections.router)
api_router.include_router(oauth.router)
api_router.include_router(agent_configs.router)
api_router.include_router(knowledge_items.router)
