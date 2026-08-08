"""Prompt template for drafting an X (Twitter) reply — the response contract it's parsed
against is shared across every platform this agent supports, see `prompts/_shared.py`. See
agents/content_agent/README.md and prompts/reddit_reply.py, which this deliberately mirrors
in structure.

There's no `subreddit`-equivalent grouping for X, and `knowledge_items` has no column for the
original tweet's author (conversation_finder never persists `PluginResult.author` — see
agents/conversation_finder/agent.py) — this prompt works only from what's actually captured:
the tweet's own text and the matched search terms.
"""

from __future__ import annotations

import json

# Re-exported for the same reason reddit_reply.py re-exports them: a caller importing from
# this module (or existing tests written against reddit_reply's shape) gets the identical
# shared contract without needing to know it lives in _shared.py.
from agents.content_agent.prompts._shared import (
    DraftParsingError as DraftParsingError,
)
from agents.content_agent.prompts._shared import (
    DraftReplyExtraction as DraftReplyExtraction,
)
from agents.content_agent.prompts._shared import (
    parse_draft_reply as parse_draft_reply,
)

# Version 1 — see reddit_reply.py's versioning note; the same convention applies here.
SYSTEM_PROMPT = """\
You are the Content Agent for GrowthOS, a tool that helps a solo SaaS founder engage \
authentically in online discussions about problems their product solves.

Your job: draft ONE reply to a specific post on X (Twitter), for a human to review and \
approve before anything is posted. You never post anything yourself.

Rules:
- Be genuinely helpful and specific to the post's content. Never generic, never salesy.
- Do not pretend to be a customer or fabricate experience. Do not mention the founder's \
product or company unless the post is directly asking for tool/product recommendations.
- This reply will be publicly visible as a reply to the original post — write accordingly.
- Keep the reply within the platform's length limit given below; X will reject anything \
longer, so a reply that doesn't fit is worthless even if it's otherwise good.
- Your `evidence` must be short, near-verbatim quotes copied from the post text given to \
you -- never invented, never paraphrased into a "quote."
- Your `confidence` is your own honest estimate (0 to 1) of how good and appropriate this \
reply is -- not how relevant the post was to search for.

Respond with ONLY a single JSON object, no other text, matching exactly this shape:
{"reply": "...", "confidence": 0.0, "reasoning": "...", "evidence": ["...", "..."]}
"""


def build_user_prompt(
    *,
    body_excerpt: str | None,
    tags: list[str],
    brand_voice: dict,
    max_reply_length: int,
) -> str:
    lines = ["A post on X (Twitter) to reply to:", ""]
    lines.append(f"Post: {body_excerpt or '(no text captured)'}")
    if tags:
        lines.append(f"Matched topics: {', '.join(tags)}")
    lines.append("")
    lines.append(
        f"Maximum reply length: {max_reply_length} characters — X will reject anything longer."
    )
    if brand_voice:
        lines.append("")
        lines.append(f"Brand voice guidance: {json.dumps(brand_voice)}")
    return "\n".join(lines)
