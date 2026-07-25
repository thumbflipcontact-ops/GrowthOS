"""See docs/errors/ERROR_HANDLING.md."""

from __future__ import annotations

from fastapi import status

from app.core.errors import (
    AuthenticationError,
    AuthorizationError,
    CapabilityNotSupported,
    GrowthOSError,
    InvalidStateTransition,
    NotFoundError,
    PluginError,
    RateLimited,
    ValidationError,
)


def test_domain_errors_carry_stable_codes_and_status() -> None:
    cases = [
        (NotFoundError("x"), "not_found", status.HTTP_404_NOT_FOUND),
        (ValidationError("x"), "validation_error", status.HTTP_422_UNPROCESSABLE_ENTITY),
        (CapabilityNotSupported("x"), "capability_not_supported", status.HTTP_409_CONFLICT),
        (InvalidStateTransition("x"), "invalid_state_transition", status.HTTP_409_CONFLICT),
        (AuthenticationError("x"), "authentication_error", status.HTTP_401_UNAUTHORIZED),
        (AuthorizationError("x"), "authorization_error", status.HTTP_403_FORBIDDEN),
    ]
    for exc, code, http_status in cases:
        assert exc.code == code
        assert exc.status_code == http_status
        assert isinstance(exc, GrowthOSError)


def test_plugin_error_carries_plugin_key_in_details() -> None:
    exc = PluginError("boom", plugin_key="reddit")
    assert exc.details["plugin_key"] == "reddit"


def test_rate_limited_is_a_plugin_error() -> None:
    exc = RateLimited("slow down", plugin_key="reddit")
    assert isinstance(exc, PluginError)
    assert exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS
