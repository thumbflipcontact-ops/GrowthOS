"""Domain exception hierarchy — see docs/errors/ERROR_HANDLING.md.

Every layer raises one of these instead of a generic Exception or a bare
fastapi.HTTPException, so there is exactly one place (register_exception_handlers) that maps
domain errors to HTTP responses.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger = structlog.get_logger()


class GrowthOSError(Exception):
    """Base for all domain errors."""

    code = "internal_error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(GrowthOSError):
    code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND


class ValidationError(GrowthOSError):
    code = "validation_error"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


class CapabilityNotSupported(GrowthOSError):
    """Raised when the plugin registry is asked for a capability a plugin doesn't
    structurally implement (see docs/plugins/PLUGIN_ARCHITECTURE.md's segmented Protocols) or
    that a project hasn't enabled at the connection level. mypy prevents most of this at the
    type-check stage for in-repo callers; this is the runtime backstop for
    dynamically-resolved lookups (e.g. by plugin_key from request data). Must never be
    silently caught and swallowed anywhere in agent or service code."""

    code = "capability_not_supported"
    status_code = status.HTTP_409_CONFLICT


class InvalidStateTransition(GrowthOSError):
    """Raised on an illegal state transition, or on a concurrency-guard version mismatch —
    see ARCHITECTURE.md §8."""

    code = "invalid_state_transition"
    status_code = status.HTTP_409_CONFLICT


class PluginError(GrowthOSError):
    """Wraps any failure from an external system call, with the originating plugin_key."""

    code = "plugin_error"
    status_code = status.HTTP_502_BAD_GATEWAY

    def __init__(
        self, message: str, *, plugin_key: str, details: dict[str, object] | None = None
    ) -> None:
        super().__init__(message, details={"plugin_key": plugin_key, **(details or {})})
        self.plugin_key = plugin_key


class RateLimited(PluginError):
    code = "rate_limited"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS


class AuthenticationError(GrowthOSError):
    code = "authentication_error"
    status_code = status.HTTP_401_UNAUTHORIZED


class AuthorizationError(GrowthOSError):
    code = "authorization_error"
    status_code = status.HTTP_403_FORBIDDEN


def register_exception_handlers(app: FastAPI) -> None:
    """The single place every domain exception is mapped to the API error envelope
    documented in docs/errors/ERROR_HANDLING.md."""

    @app.exception_handler(GrowthOSError)
    async def handle_domain_error(request: Request, exc: GrowthOSError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        if exc.status_code >= 500:
            logger.error(
                "unhandled_domain_error", code=exc.code, request_id=request_id, exc_info=exc
            )
        else:
            logger.info("domain_error", code=exc.code, request_id=request_id)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        logger.error("unexpected_error", request_id=request_id, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "details": {"request_id": request_id},
                }
            },
        )
