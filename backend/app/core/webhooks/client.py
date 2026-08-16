"""Outbound HTTP delivery for webhooks — see app/core/webhooks/dispatcher.py, the only
caller. Mirrors app/core/oauth/client.py / app/core/email/client.py's shape: a fresh
httpx.AsyncClient per call rather than a long-lived instance attribute, non-2xx and transport
errors wrapped into a subsystem-local exception rather than left as raw httpx exceptions.
Stateless (no constructor args) — unlike ResendClient (one fixed api_key/from_email reused
across many sends), every delivery here targets a different url/secret, so there's no
per-instance state worth holding.
"""

from __future__ import annotations

import httpx

from app.core.webhooks.errors import WebhookDeliveryFailed

_HTTP_TIMEOUT_SECONDS = 10.0


class WebhookHttpClient:
    async def send(self, *, url: str, headers: dict[str, str], body: bytes) -> int:
        """Returns the response status code on a 2xx response; raises WebhookDeliveryFailed
        otherwise (transport error, timeout, or non-2xx)."""
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise WebhookDeliveryFailed(f"Could not reach {url}: {exc}") from exc

        if response.status_code >= 300:
            raise WebhookDeliveryFailed(
                f"{url} returned {response.status_code}: {response.text[:500]}"
            )
        return response.status_code


__all__ = ["WebhookHttpClient"]
