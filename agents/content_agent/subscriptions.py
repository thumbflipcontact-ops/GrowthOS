"""Content Agent reacts to `knowledge_item.created` — see
docs/agents/AGENT_ARCHITECTURE.md §Communication and README.md.

Deliberately no `filter=` here. The original spec (and docs/agents/AGENT_ARCHITECTURE.md's
own worked example) filters on `payload["buying_intent"]` — but nothing populates
`buying_intent` yet (Conversation Finder has no LLM integration, see
docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md), so every event's `buying_intent`
is always `"none"`. A hardcoded buying_intent filter here would silently accept zero events,
forever, which is worse than no filter at all. Real relevance gating instead happens inside
`agent.py`'s `run()`, against the triggering item's `confidence` and this agent's own
per-project `min_confidence_for_reply` config — configurable, unlike a subscription filter.
"""

from __future__ import annotations

from agents._shared.subscriptions import AgentSubscriptions, EventSubscription

AGENT_SUBSCRIPTIONS = AgentSubscriptions(
    agent_key="content_agent",
    subscriptions=(EventSubscription(event_type="knowledge_item.created"),),
)
