from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.content_agent.config import ContentAgentConfig


def test_defaults() -> None:
    config = ContentAgentConfig()
    assert config.min_confidence_for_reply == 0.4
    assert config.max_reply_length == 10_000
    assert config.max_tweet_length == 280
    assert config.temperature == 0.7
    assert config.max_tokens == 1024


def test_accepts_full_config() -> None:
    config = ContentAgentConfig.model_validate(
        {
            "min_confidence_for_reply": 0.6,
            "max_reply_length": 500,
            "temperature": 0.2,
            "max_tokens": 300,
        }
    )
    assert config.min_confidence_for_reply == 0.6
    assert config.max_reply_length == 500
    assert config.temperature == 0.2
    assert config.max_tokens == 300


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_confidence_for_reply", -0.1),
        ("min_confidence_for_reply", 1.1),
        ("max_reply_length", 0),
        ("max_tweet_length", 0),
        ("temperature", -0.1),
        ("temperature", 1.1),
        ("max_tokens", 0),
    ],
)
def test_rejects_out_of_range_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ContentAgentConfig.model_validate({field: value})
