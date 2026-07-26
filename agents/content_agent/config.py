"""Content Agent's own config schema. See README.md §Config.

Phase 2B scope is narrower than the full agent this package's README describes: reply
drafts only, Reddit only. `content_types_enabled`/`min_buying_intent_for_reply` from the
original spec aren't here — see README.md §"What Phase 2B does not do" for why.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ContentAgentConfig(BaseModel):
    min_confidence_for_reply: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description=(
            "The triggering knowledge_item's own confidence (see "
            "agents/conversation_finder/ranking.py) below which this agent drafts nothing "
            "for it. Substitutes for the original spec's min_buying_intent_for_reply — "
            "buying_intent isn't populated by anything yet, see README.md."
        ),
    )
    max_reply_length: int = Field(
        default=10_000,
        ge=1,
        description=(
            "Matches plugins/reddit/manifest.py's reddit_reply ContentTypeSpec.max_length. "
            "Not read from the plugin catalog dynamically (see README.md's scoping note) — "
            "kept here as an explicit, self-contained limit."
        ),
    )
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    max_tokens: int = Field(default=1024, ge=1)
    banned_phrases: list[str] = Field(
        default_factory=list,
        description=(
            "Case-insensitive substrings that fail the self-check "
            "(app/services/content_self_check.py) if present in a drafted reply — see "
            "ARCHITECTURE.md §8's 'banned-phrase filter' example. Empty by default: no "
            "phrase is banned unless a project configures one."
        ),
    )
