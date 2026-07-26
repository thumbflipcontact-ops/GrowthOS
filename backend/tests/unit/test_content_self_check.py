"""Unit tests for the self-check pure function — see app/services/content_self_check.py and
ARCHITECTURE.md §8.
"""

from __future__ import annotations

from app.services.content_self_check import run_self_check


def test_a_short_clean_body_passes() -> None:
    result = run_self_check("A perfectly reasonable reply.", max_length=1000)
    assert result.passed is True
    assert result.reasons == []


def test_an_empty_body_fails() -> None:
    result = run_self_check("", max_length=1000)
    assert result.passed is False
    assert "body is empty" in result.reasons


def test_a_whitespace_only_body_fails() -> None:
    result = run_self_check("   \n\t  ", max_length=1000)
    assert result.passed is False
    assert "body is empty" in result.reasons


def test_a_body_exceeding_max_length_fails() -> None:
    result = run_self_check("x" * 101, max_length=100)
    assert result.passed is False
    assert any("max_length" in reason for reason in result.reasons)


def test_a_body_at_exactly_max_length_passes() -> None:
    result = run_self_check("x" * 100, max_length=100)
    assert result.passed is True


def test_a_banned_phrase_fails_case_insensitively() -> None:
    result = run_self_check(
        "Buy now, GUARANTEED results!", max_length=1000, banned_phrases=["guaranteed results"]
    )
    assert result.passed is False
    assert any("guaranteed results" in reason for reason in result.reasons)


def test_no_banned_phrases_configured_never_fails_on_that_check() -> None:
    result = run_self_check("Anything goes here.", max_length=1000, banned_phrases=())
    assert result.passed is True


def test_multiple_failures_are_all_reported() -> None:
    result = run_self_check(
        "guaranteed win", max_length=5, banned_phrases=["guaranteed"]
    )
    assert result.passed is False
    assert len(result.reasons) == 2


def test_blank_banned_phrases_are_ignored() -> None:
    result = run_self_check("hello world", max_length=1000, banned_phrases=["", "   "])
    assert result.passed is True
