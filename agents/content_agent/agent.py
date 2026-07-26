"""Content Agent — see README.md.

Subscription-triggered (see subscriptions.py) by `knowledge_item.created`. Loads the
triggering `knowledge_item`, drafts ONE Reddit reply for it via the configured LLM provider,
persists it as a `content_items` row (`ctx.content.create_draft`), then immediately runs the
self-check and auto-advance (`ctx.content.submit_for_review`) — matching ARCHITECTURE.md
§8's documented flow: created `draft`, advanced to `pending_review` once the self-check
passes. Never advances a draft any further than that itself — `ContentApprovalService`
(Phase 2C) owns every transition past `pending_review`. Does NOT draft outreach copy,
standalone articles, or anything for a platform other than Reddit — see README.md
§"What this agent does not do".

Imports `app.core.llm.base`'s plain dataclasses at runtime (not just under TYPE_CHECKING) to
construct the `CompletionRequest` it hands `ctx.llm.complete(...)` — an accepted, narrow
exception to agents generally avoiding backend/app imports, since ADR 0004 places the LLM
interface inside `backend/app/core/llm/` itself (there is no separate, dependency-free
"llm SDK" package the way `plugins/_shared`/`agents/_shared` exist for those boundaries).
This agent never imports a concrete provider (e.g. `AnthropicProvider`) — only the shared
interface types.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from app.core.llm.base import CompletionRequest, LLMMessage

from agents._shared.base import AgentContext, AgentResult
from agents.content_agent.config import ContentAgentConfig
from agents.content_agent.prompts.reddit_reply import (
    SYSTEM_PROMPT,
    DraftParsingError,
    build_user_prompt,
    parse_draft_reply,
)

if TYPE_CHECKING:
    from app.models.knowledge import KnowledgeItem
    from app.models.project import Project

# Phase 2B drafts Reddit replies only — see README.md. A knowledge_item from any other
# platform is skipped, not an error: other platforms legitimately exist in the schema
# (Conversation Finder can discover from any Searchable plugin), this agent just doesn't
# have a prompt template or a target_ref convention for them yet.
_SUPPORTED_PLATFORM = "reddit"
_CONTENT_TYPE = "reddit_reply"


class ContentAgent:
    key = "content_agent"
    config_schema = ContentAgentConfig

    async def run(self, ctx: AgentContext) -> AgentResult:
        config = ContentAgentConfig.model_validate(ctx.config)
        result = AgentResult()

        knowledge_item_id = _extract_knowledge_item_id(ctx.trigger_payload)
        if knowledge_item_id is None:
            result.errors.append(
                "trigger_payload is missing or has no knowledge_item_id — nothing to draft "
                "from."
            )
            return result

        item = await ctx.knowledge_base.get(knowledge_item_id)
        if item is None:
            result.errors.append(f"knowledge_item {knowledge_item_id} no longer exists.")
            return result

        result.summary = {
            "knowledge_item_id": str(item.id),
            "platform": item.platform,
            "confidence": float(item.confidence),
        }

        if item.platform != _SUPPORTED_PLATFORM:
            result.errors.append(
                f"platform {item.platform!r} is not supported yet — Phase 2B drafts "
                f"{_SUPPORTED_PLATFORM!r} replies only."
            )
            return result

        if item.confidence < Decimal(str(config.min_confidence_for_reply)):
            result.errors.append(
                f"knowledge_item confidence {item.confidence} is below "
                f"min_confidence_for_reply ({config.min_confidence_for_reply})."
            )
            return result

        if not item.title and not item.body_excerpt:
            result.errors.append(
                "knowledge_item has no title or body_excerpt — nothing to draft or cite "
                "evidence from."
            )
            return result

        request = CompletionRequest(
            messages=[
                LLMMessage(role="system", content=SYSTEM_PROMPT),
                LLMMessage(role="user", content=_user_prompt(item, ctx.project, config)),
            ],
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
        completion = await ctx.llm.complete(request)

        try:
            draft = parse_draft_reply(completion.text)
        except DraftParsingError as exc:
            result.errors.append(str(exc))
            return result

        saved = await ctx.content.create_draft(
            project_id=ctx.project.id,
            type=_CONTENT_TYPE,
            body=draft.reply,
            confidence=Decimal(str(draft.confidence)),
            reasoning=draft.reasoning,
            evidence=draft.evidence,
            target_platform=item.platform,
            target_ref=_target_ref(item),
            knowledge_item_id=item.id,
            source_agent_run_id=ctx.agent_run_id,
        )
        result.content_items_created = 1
        result.summary["content_item_id"] = str(saved.id)
        result.summary["draft_confidence"] = draft.confidence

        check = await ctx.content.submit_for_review(
            saved,
            org_id=ctx.project.org_id,
            max_length=config.max_reply_length,
            banned_phrases=config.banned_phrases,
        )
        result.summary["self_check_passed"] = check.passed
        if not check.passed:
            result.summary["self_check_reasons"] = check.reasons
        result.summary["content_item_status"] = saved.status.value
        return result


def _extract_knowledge_item_id(trigger_payload: dict | None) -> uuid.UUID | None:
    if not trigger_payload:
        return None
    raw = trigger_payload.get("knowledge_item_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def _user_prompt(item: KnowledgeItem, project: Project, config: ContentAgentConfig) -> str:
    subreddit = (
        item.platform_metadata.get("subreddit")
        if isinstance(item.platform_metadata, dict)
        else None
    )
    brand_voice = project.brand_voice if isinstance(project.brand_voice, dict) else {}
    return build_user_prompt(
        subreddit=subreddit,
        title=item.title,
        body_excerpt=item.body_excerpt,
        tags=item.tags,
        brand_voice=brand_voice,
        max_reply_length=config.max_reply_length,
    )


def _target_ref(item: KnowledgeItem) -> str | None:
    """Reddit's own reply-target reference (a `thing_id` like `t3_abc123`) — see
    plugins/reddit/plugin.py's `_to_plugin_result` and `Publishable.publish()`'s
    `target_ref` contract. Reading `platform_metadata["thing_id"]` here (Reddit-specific
    knowledge) is this agent's own job, not the platform's — see README.md's scoping note;
    `KnowledgeItem.platform_metadata` itself stays opaque everywhere else."""
    if not isinstance(item.platform_metadata, dict):
        return None
    thing_id = item.platform_metadata.get("thing_id")
    return thing_id if isinstance(thing_id, str) else None


AGENT = ContentAgent()
