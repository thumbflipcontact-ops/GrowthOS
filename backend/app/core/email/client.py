"""Resend-backed transactional email client. The only code in the system that calls Resend's
API — see app/core/agent_lifecycle.py for the (currently only) caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from app.core.email.errors import EmailNotConfigured, EmailSendFailed

if TYPE_CHECKING:
    from app.core.config import Settings

_HTTP_TIMEOUT_SECONDS = 10.0
_RESEND_API_URL = "https://api.resend.com/emails"


class ResendClient:
    """One instance per call site, not a held singleton — mirrors app/core/oauth/client.py's
    OAuthClient shape: explicit `api_key`/`from_email` args (from Settings at the construction
    site, never anything else), a fresh httpx.AsyncClient per send rather than a long-lived
    instance attribute."""

    def __init__(self, *, api_key: str, from_email: str) -> None:
        self.api_key = api_key
        self.from_email = from_email

    @classmethod
    def from_settings(cls, settings: Settings) -> ResendClient:
        """Raises EmailNotConfigured at first use if RESEND_API_KEY/RESEND_FROM_EMAIL aren't
        set — same "fail loudly at the point of use, not at import time" pattern
        BillingService._require_access_token() uses for polar_access_token."""
        if settings.resend_api_key is None or settings.resend_from_email is None:
            raise EmailNotConfigured("RESEND_API_KEY/RESEND_FROM_EMAIL are not set.")
        return cls(
            api_key=settings.resend_api_key.get_secret_value(),
            from_email=settings.resend_from_email,
        )

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "from": self.from_email,
            "to": [to],
            "subject": subject,
            "html": html_body,
        }
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(_RESEND_API_URL, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise EmailSendFailed(f"Could not reach Resend: {exc}") from exc

        if response.status_code >= 400:
            raise EmailSendFailed(
                f"Resend returned {response.status_code}: {response.text[:500]}"
            )


__all__ = ["ResendClient"]
