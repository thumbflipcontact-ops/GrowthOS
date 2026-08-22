from __future__ import annotations

import json

import pytest

from agents.content_agent.prompts.reddit_reply import (
    DraftParsingError,
    DraftReplyExtraction,
    build_user_prompt,
    parse_draft_reply,
)


def test_build_user_prompt_includes_subreddit_title_body_and_tags() -> None:
    prompt = build_user_prompt(
        subreddit="SEO",
        title="Crawl budget question",
        body_excerpt="We have millions of pages and Google isn't indexing them all.",
        tags=["crawl budget", "indexing"],
        brand_voice={},
        max_reply_length=1000,
    )
    assert "r/SEO" in prompt
    assert "Crawl budget question" in prompt
    assert "Google isn't indexing them all" in prompt
    assert "crawl budget, indexing" in prompt
    assert "1000" in prompt


def test_build_user_prompt_handles_missing_title_and_body() -> None:
    prompt = build_user_prompt(
        subreddit=None,
        title=None,
        body_excerpt=None,
        tags=[],
        brand_voice={},
        max_reply_length=500,
    )
    assert "no title" in prompt
    assert "no body text captured" in prompt


def test_build_user_prompt_includes_brand_voice_when_present() -> None:
    prompt = build_user_prompt(
        subreddit="SEO",
        title="t",
        body_excerpt="b",
        tags=[],
        brand_voice={"tone": "friendly"},
        max_reply_length=500,
    )
    assert "friendly" in prompt


def test_parse_draft_reply_accepts_a_clean_json_response() -> None:
    text = json.dumps(
        {
            "reply": "Here's a suggestion...",
            "confidence": 0.8,
            "reasoning": "The post is clearly about crawl budget.",
            "evidence": ["Google isn't indexing them all"],
        }
    )
    draft = parse_draft_reply(text)
    assert isinstance(draft, DraftReplyExtraction)
    assert draft.reply == "Here's a suggestion..."
    assert draft.confidence == 0.8
    assert draft.evidence == ["Google isn't indexing them all"]


def test_parse_draft_reply_recovers_json_wrapped_in_prose_or_fences() -> None:
    text = (
        "Sure, here's the JSON:\n```json\n"
        + json.dumps(
            {"reply": "hi", "confidence": 0.5, "reasoning": "r", "evidence": []}
        )
        + "\n```"
    )
    draft = parse_draft_reply(text)
    assert draft.reply == "hi"


def test_parse_draft_reply_raises_draft_parsing_error_on_garbage() -> None:
    with pytest.raises(DraftParsingError):
        parse_draft_reply("not json at all")


def test_parse_draft_reply_raises_on_json_missing_required_fields() -> None:
    with pytest.raises(DraftParsingError):
        parse_draft_reply(json.dumps({"reply": "hi"}))


def test_parse_draft_reply_raises_on_out_of_range_confidence() -> None:
    with pytest.raises(DraftParsingError):
        parse_draft_reply(
            json.dumps({"reply": "hi", "confidence": 5.0, "reasoning": "r", "evidence": []})
        )


def test_parse_draft_reply_parses_a_model_decline_instead_of_raising() -> None:
    # The model's own way of saying "nothing worth replying to" — see
    # agents/content_agent/agent.py's run(), which turns this into a clean skip rather than
    # treating it as a parsing failure.
    text = json.dumps(
        {"reply": "", "confidence": 0.0, "reasoning": "Not relevant to the project.", "evidence": []}
    )
    draft = parse_draft_reply(text)
    assert draft.reply == ""
    assert draft.confidence == 0.0
