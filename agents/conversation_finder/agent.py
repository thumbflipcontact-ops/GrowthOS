"""Conversation Finder — see README.md.

Schedule-triggered (see subscriptions.py — it originates a discovery cycle rather than
reacting to one). Phase 2A scope: search every connected Searchable plugin, rank results with
a deterministic keyword-relevance score, deduplicate against what's already known, persist
survivors to the knowledge base, and announce each new one with a `knowledge_item.created`
domain event. Deliberately does NOT call an LLM or populate
problem/industry/product/pain_point/buying_intent/suggested_* — see README.md §"What Phase
2A does not do" — that's a future enrichment pass.

Also persists `title`/a capped `body_excerpt`/opaque `platform_metadata` alongside every
discovery (added alongside Content Agent, Phase 2B) — grounding text and a plugin-specific
reference a later drafting agent needs, that nothing previously stored anywhere. This agent
still never interprets `platform_metadata`'s contents — it passes it through verbatim.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from plugins._shared.base import PluginQuery, Searchable

from agents._shared.base import AgentContext, AgentResult
from agents.conversation_finder.config import ConversationFinderConfig
from agents.conversation_finder.ranking import score_result

if TYPE_CHECKING:
    from app.models.project import Project

# A capped excerpt, not the full body — knowledge_items.body_excerpt exists to give a later
# drafting agent enough grounding text to cite from, not to duplicate the platform's own copy
# of a post verbatim and unbounded.
_BODY_EXCERPT_MAX_CHARS = 2000


class ConversationFinderAgent:
    key = "conversation_finder"
    config_schema = ConversationFinderConfig

    async def run(self, ctx: AgentContext) -> AgentResult:
        config = ConversationFinderConfig.model_validate(ctx.config)
        result = AgentResult()

        terms = _effective_terms(config, ctx.project)
        if not terms:
            result.errors.append(
                "No search keywords configured — set this agent's config.keywords or "
                "project.icp_config['keywords']."
            )
            return result

        query = PluginQuery(
            project_id=ctx.project.id,
            terms=terms,
            since=datetime.now(UTC) - timedelta(hours=config.lookback_hours),
            limit=config.max_results_per_platform,
        )

        plugins_searched: list[str] = []
        results_found = 0
        seen_urls: set[str] = set()

        for plugin in ctx.plugins.all_with_capability(Searchable):
            platform = plugin.manifest.key
            plugins_searched.append(platform)
            try:
                plugin_results = await plugin.search(query)
            except Exception as exc:
                # One plugin misbehaving must never fail the whole discovery cycle — mirrors
                # PluginRegistry.all_with_capability()'s own resilience contract one level up
                # (a broken plugin is skipped at construction time; a plugin that constructs
                # fine but raises from search() itself is skipped here, same principle).
                ctx.logger.warning(
                    "conversation_finder.plugin_search_failed", platform=platform, exc_info=True
                )
                # Recorded, not just logged: a run with this still shows "succeeded" (by
                # design — one plugin failing shouldn't fail the run), so without this the
                # only way to learn a search silently failed was reading worker container
                # logs directly.
                if getattr(exc, "status_code", None) == 402:
                    # A 402 from a plugin's own API client means the *platform's* shared app
                    # ran out of prepaid API credits — a billing problem on our side, not the
                    # customer's connection. Showing the raw detail on their own Agent
                    # settings page would be both confusing (reads as "your connection is
                    # broken") and something they have no way to act on, so they get a
                    # generic message while the specific one goes to operator_alerts instead.
                    result.errors.append(
                        f"{platform}: search temporarily unavailable — we've been notified "
                        "and are on it."
                    )
                    result.operator_alerts.append(
                        f"{platform} plugin out of API credits (HTTP 402): {exc}"
                    )
                else:
                    result.errors.append(f"{platform}: search failed — {exc}")
                continue

            for plugin_result in plugin_results:
                results_found += 1
                if plugin_result.url in seen_urls:
                    continue
                seen_urls.add(plugin_result.url)

                score, matched_terms = score_result(plugin_result, terms)
                if score < config.min_score_to_save:
                    continue

                saved, created = await ctx.knowledge_base.upsert_discovery(
                    project_id=ctx.project.id,
                    source_agent_run_id=ctx.agent_run_id,
                    platform=platform,
                    url=plugin_result.url,
                    tags=matched_terms,
                    confidence=Decimal(str(score)),
                    title=plugin_result.title,
                    body_excerpt=plugin_result.body[:_BODY_EXCERPT_MAX_CHARS],
                    platform_metadata=plugin_result.platform_metadata,
                )
                if created:
                    result.knowledge_items_created += 1
                    await ctx.events.publish(
                        project_id=ctx.project.id,
                        event_type="knowledge_item.created",
                        payload={
                            "knowledge_item_id": str(saved.id),
                            "platform": saved.platform,
                            "url": saved.url,
                            "buying_intent": saved.buying_intent.value,
                            "confidence": float(saved.confidence),
                            "tags": saved.tags,
                        },
                    )

        result.summary = {
            "terms": terms,
            "platforms_searched": plugins_searched,
            "results_found": results_found,
            "unique_urls": len(seen_urls),
        }
        return result


def _effective_terms(config: ConversationFinderConfig, project: Project) -> list[str]:
    if config.keywords:
        return config.keywords
    icp_config = project.icp_config if isinstance(project.icp_config, dict) else {}
    icp_keywords = icp_config.get("keywords")
    return list(icp_keywords) if isinstance(icp_keywords, list) else []


AGENT = ConversationFinderAgent()
