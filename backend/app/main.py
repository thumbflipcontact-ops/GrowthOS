"""The FastAPI application factory. See ARCHITECTURE.md §3 (system layers) and
docs/deployment/DEPLOYMENT.md.

Startup wires the database engine, discovers the installed plugin catalog (see
app/core/plugin_catalog.py — this is the "plugin_catalog manifest scan at startup" the
`backend` service in docker-compose.yml is documented as hosting), and mints a request-id
per request for error correlation (docs/errors/ERROR_HANDLING.md).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.analytics import init_analytics
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.migration_check import verify_database_is_migrated
from app.core.observability import init_error_tracking
from app.core.plugin_catalog import PluginCatalog, discover_installed_plugins, sync_catalog_to_db

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    init_error_tracking(settings, process_name="backend")
    init_analytics(settings)

    engine = create_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    await verify_database_is_migrated(engine)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    app.state.plugin_catalog = catalog
    async with app.state.session_factory() as session:
        await sync_catalog_to_db(session, catalog)
    logger.info(
        "app.started", environment=settings.environment, plugins=[m.key for m in catalog.all()]
    )

    yield

    arq_redis = getattr(app.state, "arq_redis", None)
    if arq_redis is not None:
        await arq_redis.aclose()
    await engine.dispose()
    logger.info("app.stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="GrowthOS API", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)

    settings = get_settings()
    # allow_credentials=True is required for the session cookie to actually be sent on
    # cross-origin fetch calls from the frontend — browsers refuse credentialed cross-origin
    # requests without it, regardless of SameSite. allow_origins is deliberately one fixed
    # origin (not "*", which is incompatible with allow_credentials anyway per the fetch
    # spec), read from Settings so it's an environment concern, not a code change per deploy.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request.state.request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    app.include_router(api_router)
    return app


app = create_app()
