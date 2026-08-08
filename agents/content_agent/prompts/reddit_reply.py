"""Prompt template for drafting a Reddit reply — the response contract it's parsed against
is shared across every platform this agent supports, see `prompts/_shared.py`. See
agents/content_agent/README.md and docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md.

Deliberately asks for a JSON response and parses it here, rather than using a
provider-specific structured-output/tool-calling mechanism — `app/core/llm/base.py`'s
`LLMProvider` interface is a plain-text completion API (ADR 0004's "common subset, not the
union" trade-off), so structured output is this agent's own concern, not the platform's.

Versioned by replacing this file's constants, not by editing prompt text inline elsewhere —
see docs/agents/AGENT_ARCHITECTURE.md's anatomy note on `prompts/`.
"""

from __future__ import annotations

import json

# Re-exported for backward compatibility — these used to be defined in this module directly;
# every platform's prompt module now shares one copy in _shared.py instead of each parsing
# an identical response contract independently.
from agents.content_agent.prompts._shared import (
    DraftParsingError as DraftParsingError,
)
from agents.content_agent.prompts._shared import (
    DraftReplyExtraction as DraftReplyExtraction,
)
from agents.content_agent.prompts._shared import (
    parse_draft_reply as parse_draft_reply,
)

# Version 1. Bump this comment (and consider a reddit_reply_v2.py alongside it, not a silent
# in-place rewrite) if the response contract below changes in a way that would invalidate
# how existing drafts are interpreted.
SYSTEM_PROMPT = """\
You are the Content Agent for GrowthOS, a tool that helps a solo SaaS founder engage \
authentically in online discussions about problems their product solves.

Your job: draft ONE reply to a specific Reddit post, for a human to review and approve \
before anything is posted. You never post anything yourself.

Rules:
- Be genuinely helpful and specific to the post's content. Never generic, never salesy.
- Do not pretend to be a customer or fabricate experience. Do not mention the founder's \
product or company unless the post is directly asking for tool/product recommendations.
- Keep the reply within the platform's length limit given below.
- Your `evidence` must be short, near-verbatim quotes copied from the post's title/body \
given to you -- never invented, never paraphrased into a "quote."
- Your `confidence` is your own honest estimate (0 to 1) of how good and appropriate this \
reply is -- not how relevant the post was to search for.

Respond with ONLY a single JSON object, no other text, matching exactly this shape:
{"reply": "...", "confidence": 0.0, "reasoning": "...", "evidence": ["...", "..."]}
"""


def build_user_prompt(
    *,
    subreddit: str | None,
    title: str | None,
    body_excerpt: str | None,
    tags: list[str],
    brand_voice: dict,
    max_reply_length: int,
) -> str:
    lines = ["A Reddit post to reply to:", ""]
    if subreddit:
        lines.append(f"Subreddit: r/{subreddit}")
    lines.append(f"Title: {title or '(no title)'}")
    lines.append(f"Body: {body_excerpt or '(no body text captured)'}")
    if tags:
        lines.append(f"Matched topics: {', '.join(tags)}")
    lines.append("")
    lines.append(f"Maximum reply length: {max_reply_length} characters.")
    if brand_voice:
        lines.append("")
        lines.append(f"Brand voice guidance: {json.dumps(brand_voice)}")
    return "\n".join(lines)
