"""Conversation Finder — see README.md.

Schedule-triggered (see subscriptions.py — it originates a discovery cycle rather than
reacting to one). Search every connected Searchable plugin, cheaply pre-filter with a
deterministic keyword score (ranking.py), then ask the LLM to actually judge relevance and
buying intent for whatever survives that pre-filter — one batched call per run, not one call
per candidate (see _score_candidates_with_llm) — before persisting survivors to the
knowledge base and announcing each new one with a `knowledge_item.created` domain event.

Imports `app.core.llm.base`'s plain dataclasses at runtime (not just under TYPE_CHECKING) to
construct the `CompletionRequest` it hands `ctx.llm.complete(...)` — the same narrow,
accepted exception to agents generally avoiding backend/app imports that
agents/content_agent/agent.py's own docstring documents (ADR 0004 places the LLM interface
inside backend/app/core/llm/ itself; there is no separate dependency-free "llm SDK"
package). `BuyingIntent` itself is never imported here — `_score_candidates_with_llm`'s
output stays a plain string (`LeadScore.buying_intent`), and
`KnowledgeBaseClient.upsert_discovery` (which already imports the real model) is what
converts it to the enum, keeping this agent's only backend/app dependency the same one
content_agent already established.

If LLM scoring fails outright (the call raises, or the response doesn't parse) every
pre-filtered candidate this run falls back to exactly today's deterministic keyword score —
see the try/except around _score_candidates_with_llm. LLM scoring is a pure enhancement
layer: a bad response degrades to what already shipped before it existed, never to worse.

Also persists `title`/a capped `body_excerpt`/opaque `platform_metadata` alongside every
discovery (added alongside Content Agent, Phase 2B) — grounding text and a plugin-specific
reference a later drafting agent needs, that nothing previously stored anywhere. This agent
still never interprets `platform_metadata`'s contents — it passes it through verbatim.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from plugins._shared.base import PluginQuery, PluginResult, Searchable

from agents._shared.base import AgentContext, AgentResult
from agents.conversation_finder.config import ConversationFinderConfig
from agents.conversation_finder.prompts import (
    SYSTEM_PROMPT,
    LeadScore,
    build_user_prompt,
    parse_lead_scores,
)
from agents.conversation_finder.ranking import score_result
from app.core.llm.base import CompletionRequest, LLMMessage

if TYPE_CHECKING:
    from app.models.project import Project

# A capped excerpt, not the full body — knowledge_items.body_excerpt exists to give a later
# drafting agent enough grounding text to cite from, not to duplicate the platform's own copy
# of a post verbatim and unbounded.
_BODY_EXCERPT_MAX_CHARS = 2000

# Low temperature — this is a scoring/classification task, not a creative one, same
# reasoning app/services/keyword_suggestion_service.py already applies to its own
# structured-output LLM call. max_tokens sized for up to max_results_per_platform (25)
# short LeadScore entries in one response, with headroom.
_SCORING_TEMPERATURE = 0.3
_SCORING_MAX_TOKENS = 4096


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
        # (platform, plugin_result, keyword_score, matched_terms) for everything that passed
        # the cheap keyword pre-filter — gathered across every plugin before any LLM call, so
        # one batched call can score the whole run's candidates at once.
        candidates: list[tuple[str, PluginResult, float, list[str]]] = []

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
                if score <= 0:
                    continue  # not even one configured keyword's words appear at all
                candidates.append((platform, plugin_result, score, matched_terms))

        llm_scores_by_url: dict[str, LeadScore] = {}
        if candidates:
            try:
                llm_scores_by_url = await _score_candidates_with_llm(
                    ctx, candidates=[c[1] for c in candidates], keywords=terms
                )
            except Exception:
                # A provider error or LeadScoreParsingError — either way, every candidate
                # this run falls back to its deterministic keyword score below. Never fails
                # the whole run: LLM scoring is a pure enhancement layer (see module
                # docstring), so a bad response degrades to exactly what already shipped
                # before this feature existed.
                ctx.logger.warning("conversation_finder.llm_scoring_failed", exc_info=True)
                result.errors.append(
                    "AI lead scoring was temporarily unavailable this run — falling back to "
                    "basic keyword matching."
                )

        for platform, plugin_result, keyword_score, matched_terms in candidates:
            llm_score = llm_scores_by_url.get(plugin_result.url)
            if llm_score is not None:
                confidence = Decimal(str(round(llm_score.relevance, 2)))
                buying_intent = llm_score.buying_intent
                pain_point = llm_score.reasoning
            else:
                confidence = Decimal(str(keyword_score))
                buying_intent = None
                pain_point = None

            if confidence < Decimal(str(config.min_score_to_save)):
                continue

            saved, created = await ctx.knowledge_base.upsert_discovery(
                project_id=ctx.project.id,
                source_agent_run_id=ctx.agent_run_id,
                platform=platform,
                url=plugin_result.url,
                tags=matched_terms,
                confidence=confidence,
                title=plugin_result.title,
                body_excerpt=plugin_result.body[:_BODY_EXCERPT_MAX_CHARS],
                platform_metadata=plugin_result.platform_metadata,
                buying_intent=buying_intent,
                pain_point=pain_point,
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


async def _score_candidates_with_llm(
    ctx: AgentContext, *, candidates: list[PluginResult], keywords: list[str]
) -> dict[str, LeadScore]:
    """One batched LLM call scoring every candidate at once — see prompts.py. Returns a
    dict keyed by `LeadScore.url` (the model echoes each candidate's own url back) so the
    caller can match results even if the model reorders or drops entries; a raised exception
    here (a provider error, or LeadScoreParsingError) means the caller falls every candidate
    in this run back to its deterministic keyword score instead."""
    brand_voice = ctx.project.brand_voice if isinstance(ctx.project.brand_voice, dict) else {}
    request = CompletionRequest(
        messages=[
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=build_user_prompt(
                    candidates=candidates,
                    project_name=ctx.project.name,
                    keywords=keywords,
                    brand_voice=brand_voice,
                ),
            ),
        ],
        max_tokens=_SCORING_MAX_TOKENS,
        temperature=_SCORING_TEMPERATURE,
    )
    completion = await ctx.llm.complete(request)
    await ctx.usage.record(
        org_id=ctx.project.org_id,
        project_id=ctx.project.id,
        purpose="conversation_finder.lead_scoring",
        result=completion,
        agent_run_id=ctx.agent_run_id,
    )
    scores = parse_lead_scores(completion.text)
    return {score.url: score for score in scores}


def _effective_terms(config: ConversationFinderConfig, project: Project) -> list[str]:
    if config.keywords:
        return config.keywords
    icp_config = project.icp_config if isinstance(project.icp_config, dict) else {}
    icp_keywords = icp_config.get("keywords")
    return list(icp_keywords) if isinstance(icp_keywords, list) else []


AGENT = ConversationFinderAgent()
