"""See ADR 0010 and app/core/crypto.py."""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag

from app.core.crypto import (
    derive_master_key,
    envelope_decrypt,
    envelope_encrypt,
    generate_data_key,
    rewrap_data_key,
)


def test_derive_master_key_is_32_bytes_and_deterministic() -> None:
    key = derive_master_key("any-length-secret")
    assert len(key) == 32
    assert key == derive_master_key("any-length-secret")


def test_derive_master_key_differs_for_different_secrets() -> None:
    assert derive_master_key("secret-a") != derive_master_key("secret-b")


def test_generate_data_key_is_32_bytes_and_random() -> None:
    a, b = generate_data_key(), generate_data_key()
    assert len(a) == 32
    assert a != b


def test_envelope_round_trip() -> None:
    master_key = derive_master_key("master-secret")
    plaintext = b'{"access_token": "abc123", "refresh_token": "xyz789"}'

    ciphertext, wrapped_data_key = envelope_encrypt(master_key, plaintext)
    assert ciphertext != plaintext
    assert plaintext not in ciphertext

    decrypted = envelope_decrypt(master_key, ciphertext, wrapped_data_key)
    assert decrypted == plaintext


def test_envelope_encrypt_uses_a_fresh_data_key_each_call() -> None:
    master_key = derive_master_key("master-secret")
    plaintext = b"same plaintext"

    ciphertext_a, wrapped_a = envelope_encrypt(master_key, plaintext)
    ciphertext_b, wrapped_b = envelope_encrypt(master_key, plaintext)

    assert ciphertext_a != ciphertext_b
    assert wrapped_a != wrapped_b


def test_envelope_decrypt_fails_loudly_with_the_wrong_master_key() -> None:
    ciphertext, wrapped_data_key = envelope_encrypt(derive_master_key("correct"), b"secret")
    with pytest.raises(InvalidTag):
        envelope_decrypt(derive_master_key("wrong"), ciphertext, wrapped_data_key)


def test_envelope_decrypt_fails_loudly_on_tampered_ciphertext() -> None:
    master_key = derive_master_key("master-secret")
    ciphertext, wrapped_data_key = envelope_encrypt(master_key, b"secret")

    tampered = bytearray(ciphertext)
    tampered[-1] ^= 0xFF  # flip the last byte

    with pytest.raises(InvalidTag):
        envelope_decrypt(master_key, bytes(tampered), wrapped_data_key)


def test_rewrap_data_key_lets_the_new_master_key_decrypt() -> None:
    old_master_key = derive_master_key("old-secret")
    new_master_key = derive_master_key("new-secret")
    plaintext = b"rotate me"

    ciphertext, wrapped_data_key = envelope_encrypt(old_master_key, plaintext)
    rewrapped = rewrap_data_key(old_master_key, new_master_key, wrapped_data_key)

    # The credential ciphertext itself is untouched by rotation — only the wrapped data key
    # changes, per ADR 0010's whole point.
    assert envelope_decrypt(new_master_key, ciphertext, rewrapped) == plaintext
    with pytest.raises(InvalidTag):
        envelope_decrypt(old_master_key, ciphertext, rewrapped)
