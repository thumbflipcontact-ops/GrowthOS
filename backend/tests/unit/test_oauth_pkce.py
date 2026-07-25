"""See RFC 7636 and app/core/oauth/pkce.py."""

from __future__ import annotations

from app.core.oauth.pkce import code_challenge_from_verifier, generate_code_verifier


def test_code_verifier_length_is_in_rfc_range() -> None:
    verifier = generate_code_verifier()
    assert 43 <= len(verifier) <= 128


def test_code_verifier_uses_only_unreserved_characters() -> None:
    verifier = generate_code_verifier()
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    assert set(verifier) <= allowed


def test_code_verifiers_are_random() -> None:
    assert generate_code_verifier() != generate_code_verifier()


def test_code_challenge_is_deterministic_for_the_same_verifier() -> None:
    verifier = generate_code_verifier()
    assert code_challenge_from_verifier(verifier) == code_challenge_from_verifier(verifier)


def test_code_challenge_differs_for_different_verifiers() -> None:
    a, b = generate_code_verifier(), generate_code_verifier()
    assert code_challenge_from_verifier(a) != code_challenge_from_verifier(b)


def test_code_challenge_is_unpadded_base64url() -> None:
    challenge = code_challenge_from_verifier(generate_code_verifier())
    assert "=" not in challenge
    assert "+" not in challenge
    assert "/" not in challenge


def test_code_challenge_matches_a_known_rfc7636_test_vector() -> None:
    # RFC 7636 Appendix B's example verifier/challenge pair.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert code_challenge_from_verifier(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
