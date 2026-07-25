"""Structured logging — see docs/logging/LOGGING.md.

JSON output in staging/production, human-readable colorized output locally. All application
code logs through structlog, never bare print() or %-formatted strings.
"""

import logging
import sys

import structlog

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Call once at process startup (API, scheduler, and every worker)."""

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _redact_secrets,
    ]

    if settings.is_local:
        renderer: structlog.typing.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


# Field names that must never render in a log line even if a caller accidentally passes the
# raw value in (e.g. a credential, a session token) — defense in depth alongside SecretStr
# typing in Settings. See docs/logging/LOGGING.md "What never gets logged".
_REDACTED_KEYS = {
    "password",
    "credential",
    "credentials",
    "credentials_encrypted",
    "secret_key",
    "credential_master_key",
    "anthropic_api_key",
    "openai_api_key",
    "session_token",
    "authorization",
    # OAuth2 framework (docs/auth/OAUTH2_ARCHITECTURE.md) — access/refresh tokens and the
    # per-plugin OAuth app client secret are exactly the kind of value this set exists for.
    "access_token",
    "refresh_token",
    "client_secret",
}


def _redact_secrets(
    _logger: structlog.typing.WrappedLogger,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    for key in list(event_dict):
        if key.lower() in _REDACTED_KEYS:
            event_dict[key] = "**********"
    return event_dict


def get_logger(**initial_values: object) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(**initial_values)
    return logger
