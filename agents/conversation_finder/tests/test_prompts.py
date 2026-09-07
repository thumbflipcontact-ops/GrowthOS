from __future__ import annotations

import json

import pytest
from plugins._shared.base import PluginResult

from agents.conversation_finder.prompts import (
    LeadScore,
    LeadScoreParsingError,
    build_user_prompt,
    parse_lead_scores,
)


def _candidate(url: str, *, title: str | None = "Some title", body: str = "Some body") -> PluginResult:
    return PluginResult(url=url, title=title, body=body, author=None)


def test_build_user_prompt_includes_project_name_keywords_and_each_candidate() -> None:
    prompt = build_user_prompt(
        candidates=[_candidate("https://x.invalid/1", title="Crawl budget question", body="help")],
        project_name="Acme",
        keywords=["crawl budget", "indexing"],
        brand_voice={},
    )
    assert "Acme" in prompt
    assert "crawl budget, indexing" in prompt
    assert "https://x.invalid/1" in prompt
    assert "Crawl budget question" in prompt
    assert "help" in prompt


def test_build_user_prompt_handles_missing_title() -> None:
    prompt = build_user_prompt(
        candidates=[_candidate("https://x.invalid/1", title=None)],
        project_name="Acme",
        keywords=["seo"],
        brand_voice={},
    )
    assert "(no title)" in prompt


def test_build_user_prompt_includes_brand_voice_when_present() -> None:
    prompt = build_user_prompt(
        candidates=[_candidate("https://x.invalid/1")],
        project_name="Acme",
        keywords=["seo"],
        brand_voice={"tone": "friendly"},
    )
    assert "friendly" in prompt


def test_build_user_prompt_truncates_a_long_body() -> None:
    prompt = build_user_prompt(
        candidates=[_candidate("https://x.invalid/1", body="x" * 5000)],
        project_name="Acme",
        keywords=["seo"],
        brand_voice={},
    )
    assert "x" * 5000 not in prompt
    assert "x" * 800 in prompt


def test_parse_lead_scores_accepts_the_documented_wrapped_shape() -> None:
    text = json.dumps(
        {
            "scores": [
                {
                    "url": "https://x.invalid/1",
                    "relevance": 0.8,
                    "buying_intent": "high",
                    "reasoning": "Actively looking for a solution.",
                }
            ]
        }
    )
    scores = parse_lead_scores(text)
    assert len(scores) == 1
    assert isinstance(scores[0], LeadScore)
    assert scores[0].url == "https://x.invalid/1"
    assert scores[0].relevance == 0.8
    assert scores[0].buying_intent == "high"


def test_parse_lead_scores_accepts_a_bare_array_shape() -> None:
    text = json.dumps(
        [
            {
                "url": "https://x.invalid/1",
                "relevance": 0.3,
                "buying_intent": "low",
                "reasoning": "Tangential.",
            }
        ]
    )
    scores = parse_lead_scores(text)
    assert len(scores) == 1
    assert scores[0].url == "https://x.invalid/1"


def test_parse_lead_scores_recovers_json_wrapped_in_prose_or_fences() -> None:
    payload = json.dumps(
        {
            "scores": [
                {
                    "url": "https://x.invalid/1",
                    "relevance": 0.5,
                    "buying_intent": "medium",
                    "reasoning": "r",
                }
            ]
        }
    )
    text = f"Sure, here's the JSON:\n```json\n{payload}\n```"
    scores = parse_lead_scores(text)
    assert scores[0].url == "https://x.invalid/1"


def test_parse_lead_scores_handles_multiple_entries() -> None:
    text = json.dumps(
        {
            "scores": [
                {"url": "https://x.invalid/a", "relevance": 0.9, "buying_intent": "high", "reasoning": "a"},
                {"url": "https://x.invalid/b", "relevance": 0.1, "buying_intent": "none", "reasoning": "b"},
            ]
        }
    )
    scores = parse_lead_scores(text)
    assert {s.url for s in scores} == {"https://x.invalid/a", "https://x.invalid/b"}


def test_parse_lead_scores_raises_lead_score_parsing_error_on_garbage() -> None:
    with pytest.raises(LeadScoreParsingError):
        parse_lead_scores("not json at all")


def test_parse_lead_scores_raises_on_json_missing_required_fields() -> None:
    with pytest.raises(LeadScoreParsingError):
        parse_lead_scores(json.dumps({"scores": [{"url": "https://x.invalid/1"}]}))


def test_parse_lead_scores_raises_on_out_of_range_relevance() -> None:
    with pytest.raises(LeadScoreParsingError):
        parse_lead_scores(
            json.dumps(
                {
                    "scores": [
                        {
                            "url": "https://x.invalid/1",
                            "relevance": 5.0,
                            "buying_intent": "high",
                            "reasoning": "r",
                        }
                    ]
                }
            )
        )


def test_parse_lead_scores_raises_on_invalid_buying_intent_literal() -> None:
    with pytest.raises(LeadScoreParsingError):
        parse_lead_scores(
            json.dumps(
                {
                    "scores": [
                        {
                            "url": "https://x.invalid/1",
                            "relevance": 0.5,
                            "buying_intent": "extremely-high",
                            "reasoning": "r",
                        }
                    ]
                }
            )
        )


def test_parse_lead_scores_handles_an_empty_scores_list() -> None:
    assert parse_lead_scores(json.dumps({"scores": []})) == []
