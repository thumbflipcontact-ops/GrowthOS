"""Unit tests for agents/content_agent/prompts/twitter_reply.py — mirrors test_prompts.py's
coverage of reddit_reply.py. Parsing (parse_draft_reply/DraftParsingError) is exercised there
already since both modules share the identical implementation from prompts/_shared.py; this
file only covers what's actually different about twitter_reply: build_user_prompt.
"""

from __future__ import annotations

from agents.content_agent.prompts.twitter_reply import build_user_prompt


def test_build_user_prompt_includes_body_and_tags() -> None:
    prompt = build_user_prompt(
        body_excerpt="We have millions of pages and Google isn't indexing them all.",
        tags=["crawl budget", "indexing"],
        brand_voice={},
        max_reply_length=280,
    )
    assert "Google isn't indexing them all" in prompt
    assert "crawl budget, indexing" in prompt
    assert "280" in prompt


def test_build_user_prompt_handles_missing_body() -> None:
    prompt = build_user_prompt(
        body_excerpt=None,
        tags=[],
        brand_voice={},
        max_reply_length=280,
    )
    assert "no text captured" in prompt


def test_build_user_prompt_includes_brand_voice_when_present() -> None:
    prompt = build_user_prompt(
        body_excerpt="b",
        tags=[],
        brand_voice={"tone": "friendly"},
        max_reply_length=280,
    )
    assert "friendly" in prompt


def test_build_user_prompt_never_mentions_a_subreddit() -> None:
    # There's no subreddit-equivalent grouping on X — this is the one structural difference
    # from reddit_reply.build_user_prompt's output worth pinning down explicitly.
    prompt = build_user_prompt(
        body_excerpt="b", tags=[], brand_voice={}, max_reply_length=280
    )
    assert "subreddit" not in prompt.lower()
