"""See app/core/api_keys.py."""

from __future__ import annotations

from app.core.api_keys import generate_api_key, hash_api_key, looks_like_api_key


def test_generate_api_key_round_trips_through_hash() -> None:
    full_token, key_hash, key_prefix = generate_api_key()
    assert full_token.startswith("thr_")
    assert key_prefix == full_token[:12]
    assert hash_api_key(full_token) == key_hash


def test_generate_api_key_produces_unique_tokens() -> None:
    a, _, _ = generate_api_key()
    b, _, _ = generate_api_key()
    assert a != b


def test_hash_api_key_is_deterministic() -> None:
    assert hash_api_key("thr_abc") == hash_api_key("thr_abc")


def test_hash_api_key_differs_for_different_tokens() -> None:
    assert hash_api_key("thr_abc") != hash_api_key("thr_xyz")


def test_looks_like_api_key() -> None:
    assert looks_like_api_key("thr_abc123") is True
    assert looks_like_api_key("sk-ant-abc123") is False
    assert looks_like_api_key("") is False
