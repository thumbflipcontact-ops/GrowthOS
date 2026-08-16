"""See app/core/webhooks/validation.py."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.core.webhooks.validation import validate_target_url


def test_accepts_a_normal_https_domain() -> None:
    validate_target_url("https://hooks.example.com/webhook")  # must not raise


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/webhook",  # not https
        "https://localhost/webhook",
        "https://sub.localhost/webhook",
        "https://127.0.0.1/webhook",
        "https://0.0.0.0/webhook",
        "https://10.0.0.5/webhook",
        "https://172.16.0.5/webhook",
        "https://192.168.1.5/webhook",
        "https://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
    ],
)
def test_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValidationError):
        validate_target_url(url)


def test_rejects_a_url_with_no_hostname() -> None:
    with pytest.raises(ValidationError):
        validate_target_url("https:///no-host")
