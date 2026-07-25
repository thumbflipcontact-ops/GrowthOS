"""Conversation Finder's own config schema. See README.md §Config.

Per-plugin search parameters (e.g. Reddit's subreddit allowlist) live on that plugin's own
`plugin_connections.config` — see docs/decisions/0009-plugin-config-schema-dynamic-ui.md and
plugins/reddit/manifest.py's `RedditConnectionConfig`. This agent's own config is limited to
cross-plugin behavior: which terms to search for, how far back, and how relevant a result
must be to keep.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConversationFinderConfig(BaseModel):
    keywords: list[str] = Field(
        default_factory=list,
        description=(
            "Search terms sent to every connected Searchable plugin. Falls back to "
            "project.icp_config['keywords'] if empty — see agent.py's _effective_terms()."
        ),
    )
    lookback_hours: int = Field(
        default=168,
        ge=1,
        description="How far back to search (PluginQuery.since) — default 7 days.",
    )
    max_results_per_platform: int = Field(default=25, ge=1, le=100)
    min_score_to_save: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description=(
            "The rule-based relevance score (see ranking.py) below which a discovered "
            "result is not written to the knowledge base at all. Deliberately low by "
            "default — docs/knowledge-base/KNOWLEDGE_BASE.md: 'worth writing to the "
            "knowledge base' and 'worth a human's attention' are different bars."
        ),
    )
