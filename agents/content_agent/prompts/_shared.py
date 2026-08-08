"""The response contract every per-platform prompt module in this package shares — the JSON
shape a drafting completion must parse into, regardless of which platform's SYSTEM_PROMPT
produced it. See agents/content_agent/prompts/reddit_reply.py and twitter_reply.py, which
each own their own SYSTEM_PROMPT/build_user_prompt but both parse responses through this.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, ValidationError


class DraftReplyExtraction(BaseModel):
    reply: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: list[str] = Field(default_factory=list)


class DraftParsingError(Exception):
    """The model's response text could not be parsed into a `DraftReplyExtraction` — see
    `parse_draft_reply`. A soft failure: the caller (agents/content_agent/agent.py) records
    it in `AgentResult.errors` and creates no `content_items` row, rather than raising and
    triggering an Arq retry that would likely reproduce the same malformed response."""


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_draft_reply(text: str) -> DraftReplyExtraction:
    """Parses the model's response text as a `DraftReplyExtraction`. Tries the raw text
    first; if the model wrapped the JSON in markdown fences or added surrounding prose
    despite the system prompt's instruction, falls back to extracting the first `{...}`
    block before giving up. Raises `DraftParsingError` (never propagates the underlying
    `pydantic`/`json` exception) so the caller has one exception type to catch."""
    try:
        return DraftReplyExtraction.model_validate_json(text)
    except (ValidationError, ValueError):
        pass

    match = _JSON_OBJECT_RE.search(text)
    if match is not None:
        try:
            return DraftReplyExtraction.model_validate_json(match.group(0))
        except (ValidationError, ValueError):
            pass

    raise DraftParsingError(f"Could not parse a draft reply from the model's response: {text!r}")
