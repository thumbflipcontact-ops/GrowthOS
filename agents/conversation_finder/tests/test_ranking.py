from __future__ import annotations

from plugins._shared.base import PluginResult

from agents.conversation_finder.ranking import score_result


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
    # Both results have a real (non-empty) title here, same as an actual Reddit post always
    # does — the body-only case models "this post has a title, the term just isn't in it,"
    # not "this platform has no title concept at all" (see the title-less tests below for
    # that distinct scenario, which scores differently on purpose).
    title_score, _ = score_result(_result(title="crawl budget tips"), ["crawl budget"])
    body_score, _ = score_result(
        _result(title="an unrelated title", body="crawl budget tips"), ["crawl budget"]
    )
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


def test_full_body_coverage_scores_one_when_result_has_no_title() -> None:
    # A tweet (plugins/twitter/plugin.py always sets title=None) that matches every term in
    # its body is just as relevant as a Reddit post matching every term in its title — both
    # should be able to reach a perfect score. Regression test for the bug where a title-less
    # result was denominated against _TITLE_MATCH_WEIGHT, capping it near ~0.2-0.3 no matter
    # how relevant it actually was.
    score, matched = score_result(
        _result(title=None, body="crawl budget and canonical tags"),
        ["crawl budget", "canonical tags"],
    )
    assert score == 1.0
    assert matched == ["canonical tags", "crawl budget"]


def test_empty_title_string_is_treated_the_same_as_none() -> None:
    # PluginResult.title is optional and some plugins may pass "" rather than None —
    # either way, an empty title carries no title-match credit to chase.
    score, _ = score_result(_result(title="", body="crawl budget"), ["crawl budget"])
    assert score == 1.0


def test_body_only_match_still_scores_lower_than_a_title_match_on_the_same_result() -> None:
    # The core "title beats body" signal (test_title_match_scores_higher_than_body_match)
    # must still hold *when a title is actually present* — the fix only changes the ceiling
    # for results that have no title at all, not the relative weighting when one exists.
    result = _result(title="crawl budget tips", body="crawl budget tips, also core web vitals")
    title_only_score, _ = score_result(result, ["crawl budget"])
    both_score, _ = score_result(result, ["crawl budget", "core web vitals"])
    assert title_only_score == 1.0
    assert both_score < 1.0
