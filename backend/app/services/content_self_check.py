"""The self-check `ContentDraftClient.submit_for_review` runs before auto-advancing a draft
to `pending_review` — see ARCHITECTURE.md §8: "always created in draft, immediately
auto-advanced to pending_review once the agent's own self-check passes (e.g. length limits,
banned-phrase filter)." See docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md.

Deliberately generic (content-type-agnostic) and dependency-free of any one agent's config
shape — the caller supplies the thresholds (an agent's own config, e.g.
`ContentAgentConfig.max_reply_length`/`.banned_phrases`), this module only implements the
check logic once so future content-drafting agents don't each reinvent it.

Duplicate-content detection (also named in the original content_agent spec) is deliberately
not implemented here — it would need to query recent `content_items`, a materially bigger
feature (similarity comparison, not a pure function) than length/banned-phrase checks. Noted
as remaining work, not silently dropped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(slots=True)
class SelfCheckResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def run_self_check(
    body: str, *, max_length: int, banned_phrases: Sequence[str] = ()
) -> SelfCheckResult:
    reasons: list[str] = []

    if not body.strip():
        reasons.append("body is empty")

    if len(body) > max_length:
        reasons.append(f"body exceeds max_length ({len(body)} > {max_length})")

    lowered = body.lower()
    hits = sorted({phrase for phrase in banned_phrases if phrase and phrase.lower() in lowered})
    if hits:
        reasons.append(f"body contains banned phrase(s): {', '.join(hits)}")

    return SelfCheckResult(passed=not reasons, reasons=reasons)
