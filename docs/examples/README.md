# Example configurations

Ready-to-use, schema-validated request bodies for the setup steps
`docs/beta/FIRST_RUN_CHECKLIST.md` walks through. Each file is valid JSON you can send
as-is (`curl -d @docs/examples/<file>.json ...`) — nothing needs editing to pass validation,
though you'll obviously want to change the placeholder values (subreddit names, keywords) to
match your actual use case.

Every value in these files was checked directly against the real pydantic schema it validates
against (`agents/conversation_finder/config.py`'s `ConversationFinderConfig`,
`agents/content_agent/config.py`'s `ContentAgentConfig`, `plugins/reddit/manifest.py`'s
`RedditConnectionConfig`) — not just written to look plausible.

| File | Sends to | Purpose |
|---|---|---|
| `reddit-plugin-connection.json` | `POST /api/v1/projects/{project_id}/plugin-connections` | Creates the Reddit connection row — do this *before* starting the OAuth flow (`.../plugin-connections/reddit/oauth/start`), not instead of it. `subreddits` is what Conversation Finder actually searches; an empty list is valid (the connection just returns nothing until you set it). |
| `conversation-finder-config.json` | `PUT /api/v1/projects/{project_id}/agent-configs/conversation_finder` | `keywords` — replace with terms describing the problems your product solves, not your product's name (you're searching for people describing a problem, not for your brand). `schedule_cron` (`"0 7 * * *"` = once a day at 07:00 UTC) is optional — omit it (or set `null`) and trigger runs manually instead via `POST .../runs/trigger` while you're still getting a feel for the output quality. `min_score_to_save: 0.2` is deliberately low (see `agents/conversation_finder/config.py`'s own docstring) — "worth saving" and "worth a human's attention" are different bars; you filter at review time, not discovery time. |
| `content-agent-config.json` | `PUT /api/v1/projects/{project_id}/agent-configs/content_agent` | `min_confidence_for_reply: 0.4` — raise this (e.g. `0.6`) if you want the agent to draft less often but with a higher bar. `banned_phrases` is a case-insensitive list of substrings that fail the self-check and keep a draft from ever reaching `pending_review` — a cheap, blunt safety net worth customizing for your brand voice (generic AI-tells like the examples here, or anything you specifically never want said). `schedule_cron` is `null` because this agent is event-triggered (reacts to Conversation Finder's discoveries), never schedule-triggered — see `docs/agents/AGENT_ARCHITECTURE.md`. |

## Recommended for your first week of beta

Don't set `conversation-finder-config.json`'s `schedule_cron` yet — trigger both agents
manually (`POST .../runs/trigger`) so every run is something you deliberately asked for, and
review every single draft before approving it (`docs/beta/BETA_TEST_PLAN.md`'s phased-rollout
recommendation). Turn on the schedule only once you've seen enough real output to trust the
default thresholds above — or to know which numbers you actually want to change first.
