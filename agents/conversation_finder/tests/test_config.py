from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.conversation_finder.config import ConversationFinderConfig


def test_defaults() -> None:
    config = ConversationFinderConfig()
    assert config.keywords == []
    assert config.lookback_hours == 168
    assert config.max_results_per_platform == 25
    assert config.min_score_to_save == 0.2


def test_accepts_full_config() -> None:
    config = ConversationFinderConfig.model_validate(
        {
            "keywords": ["crawl budget", "canonical tags"],
            "lookback_hours": 24,
            "max_results_per_platform": 10,
            "min_score_to_save": 0.5,
        }
    )
    assert config.keywords == ["crawl budget", "canonical tags"]
    assert config.lookback_hours == 24
    assert config.max_results_per_platform == 10
    assert config.min_score_to_save == 0.5


@pytest.mark.parametrize(
    "field,value",
    [
        ("lookback_hours", 0),
        ("max_results_per_platform", 0),
        ("max_results_per_platform", 101),
        ("min_score_to_save", -0.1),
        ("min_score_to_save", 1.1),
    ],
)
def test_rejects_out_of_range_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ConversationFinderConfig.model_validate({field: value})
