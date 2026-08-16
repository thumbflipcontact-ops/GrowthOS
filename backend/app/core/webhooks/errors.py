"""Webhook-delivery error — see app/core/webhooks/client.py.

Internal-only: caught by app/core/webhooks/dispatcher.py to drive retry/backoff, never raised
into an HTTP response — mirrors how app/core/oauth/errors.py's TokenExchangeFailed and
app/core/email/errors.py's EmailSendFailed stay subsystem-local rather than joining
app/core/errors.py's GrowthOSError hierarchy.
"""

from __future__ import annotations


class WebhookDeliveryFailed(Exception):
    """The target URL could not be reached, or returned a non-2xx response."""


__all__ = ["WebhookDeliveryFailed"]
