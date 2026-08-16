"""Email-send error hierarchy — see app/core/email/client.py.

Kept separate from app/core/errors.py's HTTP-mapped domain exceptions, the same layering
app/core/oauth/errors.py uses for OAuth-flow errors: these are transport-level errors raised by
ResendClient, caught and logged (never re-raised into a caller that would abort on them) by
app/core/agent_lifecycle.py — a failed notification must never block the disable it's reporting.
"""

from __future__ import annotations


class EmailError(Exception):
    """Base for all email-send errors."""


class EmailNotConfigured(EmailError):
    """RESEND_API_KEY / RESEND_FROM_EMAIL not set — raised at first send attempt, not at
    process startup (same "fail loudly at the point of use" pattern as BillingNotConfigured,
    app/core/errors.py)."""


class EmailSendFailed(EmailError):
    """Resend's API could not be reached, or returned a non-2xx response."""


__all__ = ["EmailError", "EmailNotConfigured", "EmailSendFailed"]
