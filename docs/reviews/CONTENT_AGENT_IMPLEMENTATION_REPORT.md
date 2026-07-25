# Content Agent Implementation Report (Phase 2B)

**Date:** 2026-07-25
**Scope:** implement Phase 2B of the Reddit Discovery → Conversation Selection → AI Draft
Generation → Human Review → Approval → Publish → Audit Trail workflow — Content Agent, a
generic LLM provider abstraction, an initial Claude implementation, Reddit-reply prompt
templates, the reply-generation pipeline, confidence scoring, evidence/reasoning attachment,
draft persistence, and read API endpoints. Explicitly excluded per this task's instructions:
auto-publishing, the human-approval workflow, any UI, and any plugin other than Reddit
(LinkedIn, X, Slack, Email).

---

## 1. Content Agent Implementation Report

### What was built

```
agents/content_agent/
├── config.py              ContentAgentConfig — min_confidence_for_reply, max_reply_length,
│                            temperature, max_tokens
├── prompts/reddit_reply.py  SYSTEM_PROMPT, build_user_prompt(), DraftReplyExtraction
│                              (the response contract), parse_draft_reply()
├── agent.py                 ContentAgent — run(ctx), AGENT singleton
├── subscriptions.py          AGENT_SUBSCRIPTIONS — knowledge_item.created, unfiltered
├── pyproject.toml             Entry point + packaging (same pattern as conversation_finder)
├── README.md                   Rewritten — real implementation, not a forward-looking spec
└── tests/
    ├── test_config.py            Config schema validation (9 tests)
    ├── test_prompts.py             Prompt building + response parsing (8 tests)
    ├── test_subscriptions.py         Unconditional-subscription contract (3 tests)
    └── test_agent.py                  End-to-end run() against mocked collaborators (10 tests)

backend/app/
├── core/llm/                    Generic LLMProvider interface — ADR 0004
│   ├── base.py                    LLMProvider Protocol, LLMMessage, CompletionRequest/Result
│   ├── anthropic_provider.py       AnthropicProvider — Claude, wraps the `anthropic` SDK
│   ├── factory.py                   build_llm_provider(settings) — resolves the primary provider
│   └── errors.py                     LLMError / LLMRequestFailed / LLMProviderNotConfigured
├── services/content_drafts.py     ContentDraftClient — AgentContext.content's first concrete
│                                    implementation; every row it writes defaults to `draft`
├── repositories/content_repository.py  ContentItemRepository
├── jobs/events.py                       run_agent_for_event — real body (was a placeholder)
├── api/v1/content_items.py               GET .../content-items[/{id}] (drafts, read-only)
└── schemas/content.py                     ContentItemResponse
```

**Schema change: `knowledge_items` and `content_items` both gained new columns** (migration
`158996aaa01b_add_content_agent_columns.py`) — see §1's "Scoping decisions" below for why
this was necessary, not optional. `knowledge_items` gained `title`, `body_excerpt`,
`platform_metadata`; `content_items` gained `confidence`, `reasoning`, `evidence`.
`Conversation Finder` (Phase 2A, already tagged `v0.4.0-conversation-finder`) was updated to
populate the three new `knowledge_items` columns — its own test suite was updated
accordingly (2 new tests, 27 → 29).

### How reply drafting flows, end to end

1. Conversation Finder (unchanged in its own logic, extended in what it persists) discovers
   a Reddit post and writes a `knowledge_items` row — now including `title`, `body_excerpt`
   (a capped excerpt of the post body), and `platform_metadata` (Reddit's `subreddit`/
   `thing_id`, opaque) — plus the `knowledge_item.created` domain event, unchanged.
2. The event dispatcher (unchanged, real since Phase 1) picks up the event and enqueues
   `run_agent_for_event("content_agent", event_id)` on the events worker.
3. `run_agent_for_event` (now real, `backend/app/jobs/events.py`) loads the event, auto-
   provisions a `content_agent` `agent_configs` row for the project if none exists yet
   (mirroring the on-demand trigger endpoint's own provisioning — via the new
   `AgentConfigRepository.get_or_create`), writes an `agent_runs` row (`status=running`),
   builds a real `AgentContext` (this time including a real `AnthropicProvider` and the new
   `ContentDraftClient`), and calls `agent.run(ctx)`.
4. `ContentAgent.run()` reads `knowledge_item_id` from `ctx.trigger_payload`, loads the item
   via `ctx.knowledge_base.get(id)`, and skips (recording why in `AgentResult.errors`,
   creating no draft) if: the platform isn't `"reddit"`, `confidence` is below
   `min_confidence_for_reply`, or there's no `title`/`body_excerpt` to draft from.
5. Otherwise it builds a prompt from the item's title/body excerpt/tags and the project's
   `brand_voice`, calls `ctx.llm.complete(...)` (Claude), and parses the response as JSON
   into `reply`/`confidence`/`reasoning`/`evidence`. A response that fails to parse is a
   soft failure — recorded in `AgentResult.errors`, no draft written, run still `succeeded`.
6. A successfully parsed draft is persisted via `ctx.content.create_draft(...)` —
   `target_ref` is Reddit's `thing_id`, read from `knowledge_item.platform_metadata`.
7. The job records `succeeded`/`failed` on the `agent_runs` row and commits, identically to
   `run_scheduled_agent`'s pattern.

### Scoping decisions (read before assuming this agent does what the original spec implied)

**A real schema gap had to be closed before this agent could draft anything real.**
`knowledge_items` (as shipped in Phase 2A) stored `platform`/`url`/`tags`/`confidence` —
never the post's own title or body text, and never the plugin-specific reference (Reddit's
`thing_id`) needed to reply to it. Both were discarded by `plugins/reddit/plugin.py`'s
`PluginResult` on the way into the database. Without them, Content Agent would have nothing
to draft from and no citable evidence — directly failing requirements 6 and 7 (confidence
scoring, evidence/reasoning). This was found empirically while implementing, not
speculated — see `docs/knowledge-base/KNOWLEDGE_BASE.md`'s Phase 2B note and
`docs/database/SCHEMA.md`. The fix: three new, nullable/defaulted columns
(`title`/`body_excerpt`/`platform_metadata`), populated by a small, additive change to
Conversation Finder's own `agent.py` (it already had `PluginResult.title`/`.body`/
`.platform_metadata` in hand at scoring time — this was a persistence gap, not a discovery
gap). This is exactly the kind of "concrete implementation issue" this task's instructions
authorize extending the architecture for, and is called out here prominently rather than
buried in a diff.

**`AgentContext` gained a `content` field, because none of the original design's fields let
an agent write `content_items` at all.** `docs/agents/AGENT_ARCHITECTURE.md`'s documented
`AgentContext` shape lists `knowledge_base` but nothing analogous for `content_items` — a
second gap of the same kind Phase 2A found for `knowledge_base` itself (added there from
`object`). `ContentDraftClient` is the first concrete implementation, mirroring
`KnowledgeBaseClient`'s shape and constraints exactly: it is architecturally incapable of
writing anything but `status="draft"` — no method on it accepts or sets a status.

**Reddit-specific logic lives in this agent's own code, not in core platform code — by
design, not by accident.** `ContentAgent` reads `knowledge_item.platform_metadata["thing_id"]`
when `platform == "reddit"` to set `target_ref`. This is Reddit-specific knowledge, but it
lives in `agents/content_agent/agent.py`, never in `backend/app/core/` or
`backend/app/services/` — `platform_metadata` itself stays opaque everywhere in core
platform code (`KnowledgeBaseClient`, `KnowledgeItemRepository`, the API schema) exactly as
it was in Phase 2A. An *agent* being aware of a specific platform's reference format is the
same category of thing as a *plugin* implementing a specific platform's API — it's the
agent's job to decide what to do with a platform it's been told to draft for, not the
platform's job to know Reddit exists. See `docs/plugins/PLUGIN_ARCHITECTURE.md`'s
"no plugin-specific logic outside the plugin" rule — this doesn't violate it, because no
platform code branches on `platform == "reddit"`; only this one agent's own module does,
for its own stated, narrow (Phase 2B) purpose.

**No `buying_intent` subscription filter — the originally-envisioned design doesn't work
with what actually exists yet.** `docs/agents/AGENT_ARCHITECTURE.md`'s worked example filters
`knowledge_item.created` by `payload["buying_intent"] in (medium, high)`. Conversation Finder
has no LLM integration (Phase 2A, explicitly), so every `knowledge_item` it writes has
`buying_intent="none"` — a hardcoded filter on that field would silently accept zero events,
forever, and Content Agent would never run. `agents/content_agent/subscriptions.py`
subscribes unconditionally instead, and `run()` gates relevance against the item's own
`confidence` (a real, populated field) and this agent's `min_confidence_for_reply` config —
functionally equivalent gatekeeping, using the field that's actually populated.

**No self-check, no promotion past `draft` — an explicit instruction, not a simplification
of convenience.** The pre-existing spec for this agent describes a length/banned-phrase/
duplicate-content self-check before advancing `draft → pending_review`. This task's
instructions are explicit: every draft stays in `draft` until a human explicitly approves
it, full stop, and the approval workflow itself is out of scope. So there is no promotion
step at all — `ContentDraftClient.create_draft` never sets a status, and nothing anywhere
in this phase's code ever updates `content_items.status` after creation.

**Structured output via prompt-and-parse, not a provider-specific mechanism.**
`backend/app/core/llm/base.py`'s `LLMProvider.complete()` is a plain-text completion API —
no tool-calling, no provider-specific JSON mode. `agents/content_agent/prompts/
reddit_reply.py`'s system prompt asks Claude to respond with only a JSON object matching a
documented shape, and `parse_draft_reply()` parses it (with one fallback: extracting the
first `{...}` block if the model wraps the JSON in prose or markdown fences despite the
instruction not to). This keeps the shared `LLMProvider` interface a genuine common subset
(ADR 0004's accepted trade-off) rather than growing a Claude-specific escape hatch on day one.

**Only Claude is implemented; only `complete()` exists on the interface.** OpenAI
(ADR 0004's documented secondary provider) has no implementation —
`app/core/llm/factory.py` raises `LLMProviderNotConfigured` if `llm_primary_provider` is set
to it. `embed()` (also named in ADR 0004, for `knowledge_items.embedding`) isn't part of the
`LLMProvider` Protocol at all yet — nothing needs it until embeddings/semantic search work is
actually in scope. Both are additive to add later; neither blocks Content Agent.

**`max_reply_length` is a static config number, not read from `plugin_catalog` dynamically.**
The original spec says this agent "reads `plugin_catalog.content_types`... to know target-
platform constraints." Phase 2B's `ContentAgentConfig.max_reply_length` instead just matches
`plugins/reddit/manifest.py`'s declared `reddit_reply` max length as a literal default —
simpler, and sufficient for a single-platform scope; wiring live `PluginCatalog` access into
`AgentContext` for one config value wasn't judged worth the added plumbing yet.

---

## 2. Architecture compliance summary

| Requirement | Compliance |
|---|---|
| Use the existing Knowledge Base | **Yes.** Reads the triggering item exclusively via `ctx.knowledge_base.get(id)` (a new method on the existing client, not a new access path) — never queries `knowledge_items` directly. |
| Consume `knowledge_item.created` through the existing event bus | **Yes, verified against the real mechanism.** `agents/content_agent/subscriptions.py` is discovered via the same `growthos.agents` entry-point scan as Conversation Finder's; `run_agent_for_event` is invoked by the real, unchanged `EventDispatcher`/`dispatch_domain_events` — no new dispatch path was built. |
| Use the existing Agent framework | **Yes.** `ContentAgent` implements the same `Agent` Protocol (`key`, `config_schema`, `run(ctx) -> AgentResult`) as Conversation Finder; `AgentContext`/`AgentResult` are extended additively (`content`, `trigger_payload`), never replaced or forked. |
| Do not bypass the Plugin SDK | **Yes, by never touching it.** This agent makes zero plugin calls — no `search()`, no `publish()`. `target_platform`/`target_ref` come from data already captured by Conversation Finder via the SDK, not a live call. |
| Do not publish anything automatically | **Yes.** No code path in this phase calls any plugin's `publish()`, enqueues a publish job, or references `app/jobs/publish.py`. |
| Every generated reply remains in Draft state until explicitly approved | **Yes, architecturally, not just by convention.** `ContentDraftClient.create_draft` has no `status` parameter — every row it writes gets the model's own default (`draft`). No code anywhere in this phase ever executes an `UPDATE content_items SET status = ...`. |
| Maintain tenant isolation | **Yes.** Every write is scoped by `project_id` (`ContentDraftClient.create_draft(project_id=...)`, `KnowledgeBaseClient.get` reads a row already scoped to the project the triggering event belongs to); the new `GET .../content-items/{id}` endpoint uses `ContentItemRepository.get_scoped(project_id, item_id)`, returning 404 (not another project's row) for a mismatched id — tested explicitly. |
| Preserve all ADRs and architectural decisions | **Yes.** ADR 0004 (LLM provider abstraction): implemented as specified, `ctx.llm.complete(...)` only, no direct SDK import in agent code. ADR 0006 (event-driven communication): Content Agent has zero reference to Conversation Finder or any other agent. ADR 0008 (plugin-contributed content types): `content_items.type = "reddit_reply"` stays `text`, matching Reddit's own declared content type. |
| Continue strict typing, comprehensive testing, documentation standards | **Yes** — see §3. `mypy --strict` clean across every new/changed backend file (82 files) and the entirety of `agents/_shared`, `agents/conversation_finder`, `agents/content_agent` including their own test suites (25 files). `ruff check` clean except two pre-existing findings in files this task didn't touch. Documentation: this report, `agents/content_agent/README.md` (new), `docs/decisions/0004-llm-provider-abstraction.md` (implementation addendum, matching the precedent set for ADR 0005), `docs/database/SCHEMA.md` and `docs/knowledge-base/KNOWLEDGE_BASE.md` (new-column notes), `docs/agents/AGENT_ARCHITECTURE.md` (roster + worked-example note), `ROADMAP.md` (step 5 marked fully done), `backend/README.md` (structure updated), `CHANGELOG.md` (`[0.5.0]` entry). |
| No auto-publishing / approval workflow / UI / other plugins | **Yes, confirmed by absence.** No `ContentApprovalService`, no approve/reject endpoint, no frontend code, no LinkedIn/X/Slack/Email plugin or plugin-specific code anywhere in this phase's diff. |

No frozen architectural decision, ADR, or locked decision
(`docs/architecture/LOCKED_DECISIONS.md`) was touched, reinterpreted, or worked around.

---

## 3. Test results

**53 new tests written for this work, all passing, zero regressions anywhere else:**

- `agents/content_agent/tests/` — **30 passed**:
  - `test_config.py` (9) — defaults, full-config acceptance, out-of-range rejection for
    every bounded field.
  - `test_prompts.py` (8) — user-prompt construction (subreddit/title/body/tags/brand-voice/
    length-limit, and graceful handling of missing title/body), clean-JSON parsing,
    recovery from JSON wrapped in prose/markdown fences, and rejection (as
    `DraftParsingError`) of garbage text, missing required fields, and out-of-range
    confidence.
  - `test_subscriptions.py` (3) — subscribes to the right event type, matches regardless of
    `buying_intent` (including its absence), doesn't match an unrelated event type.
  - `test_agent.py` (10) — missing/unknown trigger payload, unsupported platform skipped
    without calling the LLM, below-threshold confidence skipped without calling the LLM, no
    grounding text skipped without calling the LLM, a successful completion produces a
    fully-populated draft (every field asserted), the system+user messages sent to the LLM
    are well-formed, a missing `thing_id` yields a null `target_ref` (not an error), an
    unparseable LLM response records an error and creates no draft (but the LLM *was*
    called — only parsing failed), and the result summary reports the triggering item and
    the draft.
- `backend/tests/` new files — **23 passed**:
  - `test_llm_anthropic_provider.py` (7, unit) — system/user message construction, omitting
    the `system` param when there's no system message, joining multiple system messages,
    extracting text/model/stop-reason/token-usage from the response, joining multiple text
    content blocks, and wrapping both a non-2xx response and a connection error as
    `LLMRequestFailed`.
  - `test_llm_factory.py` (2, unit) — builds a real `AnthropicProvider` for the default
    config, raises `LLMProviderNotConfigured` for `llm_primary_provider="openai"`.
  - `test_run_agent_for_event_job.py` (6, integration) — full event-to-draft run against a
    real `AnthropicProvider` wired to `httpx.MockTransport` (a real HTTP round-trip, never a
    live network call — same technique as the unit tests above): drafts and persists a
    content item with every field correct and auto-provisions the `content_agent`
    `agent_configs` row exactly once; no-ops for a missing event; skips when the agent is
    disabled for the project; records a `failed` run and re-raises when the LLM call itself
    fails; records a `succeeded` run with zero drafts when the response is unparseable; and
    skips a low-confidence item without ever calling the LLM (asserted via the mock
    transport's own call log, not just the result).
  - `test_content_drafts_client.py` (2, integration) — writes a `draft`-status row with
    every field populated (against real `knowledge_items`/`agent_runs` FKs, not fabricated
    ids), and defaults `reasoning`/`evidence`/`target_platform`/`target_ref`/
    `knowledge_item_id`/`created_by_agent_run_id` correctly when omitted.
  - `test_content_items_api.py` (6, integration) — lists drafts, filters by status, retrieves
    one by id, 404s for an unknown id, 404s for an id belonging to a different project
    (the tenant-isolation check), and requires project access.
- `agents/conversation_finder/tests/` — **2 new tests** (27 → 29): title/body_excerpt/
  platform_metadata pass through verbatim from `PluginResult`, and `body_excerpt` is capped
  at 2000 characters.

**Full suite totals:**
- `cd backend && pytest`: **230 passed** (203 before this task).
- `pytest agents plugins` (from repo root): **104 passed** (74 before this task).

**Lint/type-check:**
- `ruff check` — clean across every new/changed file. Two pre-existing findings remain in
  files this task didn't touch (`agents/_shared/subscriptions.py`'s one long line;
  `app/core/oauth/client.py` and three other pre-existing files' import-sort findings,
  already noted in the Phase 2A report).
- `mypy --strict` — clean across all 82 files in `backend/app/` and all 25 source files
  across `agents/_shared`, `agents/conversation_finder`, `agents/content_agent` (including
  every test file in all three).

**End-to-end wiring, verified against the real mechanism, not asserted:**
```
$ discover_agent_subscriptions() → [('content_agent', (knowledge_item.created,)),
                                     ('conversation_finder', ())]
$ load_agent('content_agent').key → 'content_agent'
```
`test_run_agent_for_event_job.py` exercises the entire real chain — a `domain_events` row →
`AgentConfigRepository.get_or_create` → a real `AnthropicProvider` HTTP round-trip (mocked
transport, real request/response shape) → `content_agent.run()` → a `content_items` row →
an `agent_runs` row — with no fakes standing in for any platform component, only the
external Anthropic API surface (mocked exactly like the Reddit plugin's own tests mock
Reddit's API).

---

## 4. API documentation

Matches the resource paths `docs/api/API_DESIGN.md` already specified for this area
(written well before this phase). Both routes are project-scoped and depend on
`require_project_access`, exactly like every existing route. Read-only, by design — nothing
in this phase writes `content_items` through the API.

| Method & path | Purpose |
|---|---|
| `GET /api/v1/projects/{project_id}/content-items?status=&limit=&offset=` | List this project's drafts, newest first. `status` filters to a `content_item_status` value (`draft`, `pending_review`, ... — all valid today, though only `draft` rows exist until Phase 2C). |
| `GET /api/v1/projects/{project_id}/content-items/{item_id}` | Retrieve one draft, including `confidence`/`reasoning`/`evidence`/`target_platform`/`target_ref`. 404 if the id doesn't exist or belongs to a different project. |

Example: after Conversation Finder has discovered something and Content Agent has reacted to
it (both automatic, via the event bus — no manual step), read the resulting draft:

```bash
curl http://localhost:8000/api/v1/projects/{project_id}/content-items \
  --cookie "growthos_session=<cookie>"
# → [{"id": "...", "status": "draft", "type": "reddit_reply",
#     "body": "...", "confidence": "0.75", "reasoning": "...",
#     "evidence": ["a short quote from the source post"],
#     "target_platform": "reddit", "target_ref": "t3_abc123", ...}]

curl http://localhost:8000/api/v1/projects/{project_id}/content-items/{item_id} \
  --cookie "growthos_session=<cookie>"
```

To see this happen for real end to end (not just via tests): configure and trigger
Conversation Finder (see `docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md`'s API
docs), wait for the event dispatcher's next cycle (≤5 seconds) plus one events-worker job,
then list `content-items` — no additional trigger call is needed for Content Agent itself,
since it's subscription-triggered, not schedule-triggered.

---

## 5. Remaining work before Phase 2C (Approval Workflow)

- **`ContentApprovalService` and the approve/reject API endpoints.** The database-level
  concurrency guard (`content_items.version`, the `review_fields_consistent` constraint) has
  existed since Phase 1; the service and endpoints that use it correctly (per
  `docs/api/API_DESIGN.md`'s documented 409-on-version-mismatch contract) are not built.
- **The publish worker (`app/jobs/publish.py`).** Still a placeholder — the only job left
  with no real agent/service to invoke it, since publishing an approved draft is exactly
  what Phase 2C's approval transition would trigger.
- **A UI for reviewing drafts.** The read API (§4) is `curl`-only today; nothing renders
  `evidence`/`reasoning`/`confidence` for a human to actually look at outside a raw JSON
  response.
- **A real, connected Reddit account and a real Anthropic API key.** Nothing in this phase
  or the last one has made a real network call outside tests — Content Agent has never
  actually drafted from a real Reddit thread using a real Claude call.
- **Outreach drafts and article drafts** — the rest of the original Content Agent spec.
  Outreach needs `contacts`/`outreach_assistant` (Phase 2, not built); article drafts need
  cross-`knowledge_item` pattern mining (arguably a `knowledge_base_agent` concern). Neither
  was in scope for this task.
- **Other plugins' reply formats** (LinkedIn, X, Slack, Email) — explicitly out of scope
  here; `_SUPPORTED_PLATFORM = "reddit"` in `agent.py` is the one line that would need a
  real per-platform strategy (prompt template + `target_ref` convention) to extend.
- **An LLM-based enrichment pass for `knowledge_items.problem`/`industry`/`product`/
  `pain_point`/`buying_intent`.** Still nothing populates these — Content Agent's own
  drafting doesn't need them (it reads `title`/`body_excerpt` directly), but the originally-
  envisioned `buying_intent`-based subscription filter can't be restored until something
  does. Whether that's Content Agent's own job or a separate enrichment agent's is still an
  open design question, deliberately not decided by this task.
- **OpenAI provider implementation and `LLMProvider.embed()`.** Config-plumbing-ready
  (`Settings.openai_api_key`, `llm_primary_provider`), not built — see §1's scoping notes.
- **Observability** — `ARCHITECTURE.md` §10's planned OpenTelemetry spans don't wrap LLM
  calls or this agent's work yet.

None of the above block Phase 2C from being designed — they're the concrete list of what it
(and whatever comes after it) would need this phase's code to actually do, once building it
is back in scope.
