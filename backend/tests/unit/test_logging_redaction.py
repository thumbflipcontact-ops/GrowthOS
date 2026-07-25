"""See docs/logging/LOGGING.md "What never gets logged". No test previously existed for
_redact_secrets at all; added alongside the OAuth2 framework's access_token/refresh_token/
client_secret additions to _REDACTED_KEYS so the redaction behavior itself is verified, not
just the presence of the new keys in the set."""

from __future__ import annotations

from app.core.logging import _redact_secrets


def test_redacts_oauth_token_fields() -> None:
    event_dict = _redact_secrets(
        None, "info", {"access_token": "at-123", "refresh_token": "rt-456", "client_secret": "s3cr3t"}
    )
    assert event_dict["access_token"] == "**********"
    assert event_dict["refresh_token"] == "**********"
    assert event_dict["client_secret"] == "**********"


def test_redaction_is_case_insensitive() -> None:
    event_dict = _redact_secrets(None, "info", {"Access_Token": "at-123"})
    assert event_dict["Access_Token"] == "**********"


def test_does_not_touch_unrelated_fields() -> None:
    event_dict = _redact_secrets(None, "info", {"plugin_key": "reddit", "project_id": "abc"})
    assert event_dict == {"plugin_key": "reddit", "project_id": "abc"}


def test_still_redacts_pre_existing_keys() -> None:
    event_dict = _redact_secrets(None, "info", {"password": "hunter2", "credentials_encrypted": b"x"})
    assert event_dict["password"] == "**********"
    assert event_dict["credentials_encrypted"] == "**********"
