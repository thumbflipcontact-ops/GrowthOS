from __future__ import annotations

from agents.conversation_finder.ranking import score_result
from plugins._shared.base import PluginResult


def _result(*, title: str | None = "", body: str = "") -> PluginResult:
    return PluginResult(url="https://example.invalid/x", title=title, body=body, author=None)


def test_no_terms_scores_zero() -> None:
    score, matched = score_result(_result(title="anything"), [])
    assert score == 0.0
    assert matched == []


def test_no_match_scores_zero() -> None:
    score, matched = score_result(_result(title="cats and dogs", body="a whole post"), ["indexing"])
    assert score == 0.0
    assert matched == []


def test_title_match_scores_higher_than_body_match() -> None:
    title_score, _ = score_result(_result(title="crawl budget tips"), ["crawl budget"])
    body_score, _ = score_result(_result(body="crawl budget tips"), ["crawl budget"])
    assert title_score > body_score
    assert title_score == 1.0


def test_full_title_coverage_scores_one() -> None:
    score, matched = score_result(
        _result(title="crawl budget and canonical tags"), ["crawl budget", "canonical tags"]
    )
    assert score == 1.0
    assert matched == ["canonical tags", "crawl budget"]


def test_partial_coverage_scores_between_zero_and_one() -> None:
    score, matched = score_result(
        _result(title="crawl budget only"), ["crawl budget", "core web vitals"]
    )
    assert 0.0 < score < 1.0
    assert matched == ["crawl budget"]


def test_matching_is_case_insensitive() -> None:
    score, matched = score_result(_result(title="Crawl Budget"), ["crawl budget"])
    assert score == 1.0
    assert matched == ["crawl budget"]


def test_matched_terms_are_deduplicated_and_sorted() -> None:
    score, matched = score_result(
        _result(title="crawl budget", body="crawl budget again"),
        ["crawl budget", "crawl budget"],
    )
    assert matched == ["crawl budget"]


def test_none_title_does_not_raise() -> None:
    # `title` is the only optional field on PluginResult — `body` is always a str, possibly
    # empty (see plugins/_shared/base.py).
    score, matched = score_result(_result(title=None, body=""), ["indexing"])
    assert score == 0.0
    assert matched == []


def test_blank_terms_are_ignored() -> None:
    score, matched = score_result(_result(title="crawl budget"), ["crawl budget", "  ", ""])
    assert matched == ["crawl budget"]
