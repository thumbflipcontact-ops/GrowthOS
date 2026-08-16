"""Basic SSRF guard for `webhook_subscriptions.target_url` — see
app/services/webhook_subscription.py, the only caller.

Literal-string validation only: rejects an obviously-private hostname/IP at creation time.
NOT DNS-rebinding-proof — a hostname that only resolves to a private IP at request time (not
creation time) would slip past this check, since it never actually resolves DNS here. A
reasonable deferral at this scale (target_url is supplied by a project's own owner, not an
untrusted third party) — fully closing this would mean resolving before every dispatch attempt
and re-checking the resolved IP, worth doing if this is ever opened to less-trusted callers.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from app.core.errors import ValidationError

_BLOCKED_HOSTNAMES = {"localhost", "0.0.0.0"}  # noqa: S104 — a literal to reject, not to bind


def validate_target_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValidationError("target_url must use https.", details={"target_url": url})

    hostname = parsed.hostname
    if not hostname:
        raise ValidationError("target_url has no hostname.", details={"target_url": url})

    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(".localhost"):
        raise ValidationError(
            "target_url may not point at localhost.", details={"target_url": url}
        )

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return  # a normal domain name, not a literal IP — nothing further to check here
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        raise ValidationError(
            "target_url may not point at a private or reserved IP address.",
            details={"target_url": url},
        )


__all__ = ["validate_target_url"]
