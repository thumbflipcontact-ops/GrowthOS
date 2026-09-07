"use client";

import { useState } from "react";
import { SourcePost, originalPostUrl } from "@/components/SourcePost";
import { ApiError, api } from "@/lib/api-client";
import type { ContentItem } from "@/lib/types";

// X's own platform policy (Feb 2026) blocks a programmatic reply/quote unless the target
// post's author already @mentioned this account or quoted it first — every organically
// discovered post fails that by construction, so the backend never even attempts to
// auto-publish a twitter item. Reddit is manual-only too, since most projects have no
// connected (Publishable) Reddit account — search works without one, but posting still
// needs a real OAuth connection few projects will have. See backend/app/services/
// content_approval.py's MANUAL_PUBLISH_ONLY_PLATFORMS, the source of truth this mirrors —
// this is the frontend's matching list: which platforms an approved item needs a human to
// post themselves, rather than waiting on a publish job.
export const MANUAL_PUBLISH_ONLY_PLATFORMS = new Set(["twitter", "reddit"]);

// item.source_confidence — how well the original post matched the search keywords (0-1,
// agents/conversation_finder/ranking.py's score_result()) — deliberately distinct from the
// "Draft quality" number next to it, which rates the AI's own reply, not the lead itself.
export function LeadMatchBadge({ score }: { score: string }) {
  const pct = Math.round(Number(score) * 100);
  const badgeClass = pct >= 70 ? "badge-success" : pct >= 40 ? "badge-warn" : "badge-muted";
  return <span className={`badge ${badgeClass}`}>Lead match: {pct}%</span>;
}

// item.source_buying_intent — the LLM lead-scoring pass's own judgment
// (agents/conversation_finder/prompts.py), "none"/"low"/"medium"/"high". Only "high"/"medium"
// get a badge — "low"/"none" aren't worth calling out, and older/fallback items (no LLM pass)
// have this null and render nothing here, exactly as before this feature existed.
export function LeadIntentBadge({ intent }: { intent: string }) {
  if (intent !== "high" && intent !== "medium") return null;
  const badgeClass = intent === "high" ? "badge-success" : "badge-warn";
  const label = intent === "high" ? "High intent" : "Medium intent";
  return <span className={`badge ${badgeClass}`}>{label}</span>;
}

// item.source_pain_point — the LLM lead-scoring pass's one-sentence reasoning for its score,
// written for a person deciding whether to reply (see prompts.py's SYSTEM_PROMPT) — the
// closest honest equivalent to MentionCatch's own "why this lead" line, without claiming the
// separate Buying Intent / Problem Fit / Urgency breakdown this doesn't produce.
export function WhyThisLead({ pain_point }: { pain_point: string }) {
  return (
    <p className="muted" style={{ fontSize: 13 }}>
      <strong>Why this lead:</strong> {pain_point}
    </p>
  );
}

// An approved item whose platform this system can't auto-publish to (see
// MANUAL_PUBLISH_ONLY_PLATFORMS) — copy the text, open the original post, post it yourself,
// then confirm it here so it stops showing up as waiting on you. Lives on the Ready to Post
// page (frontend/app/ready-to-post/page.tsx), not the Approvals page — a customer's own
// framing of the two-step flow ("first I decide, then I actually go post it") led to giving
// each step its own tab instead of stacking both under one scroll.
export function ReadyToPostCard({
  item,
  projectId,
  onResolved,
}: {
  item: ContentItem;
  projectId: string;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const postUrl = originalPostUrl(item);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(item.body);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy — select and copy the text manually.");
    }
  }

  async function handleMarkPosted() {
    setBusy(true);
    setError(null);
    try {
      await api.markContentItemPublished(projectId, item.id, item.version);
      onResolved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update.");
      setBusy(false);
    }
  }

  async function handleDiscard() {
    setBusy(true);
    setError(null);
    try {
      await api.archiveContentItem(projectId, item.id, item.version, "Discarded, not posted.");
      onResolved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not discard.");
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="row">
        <div className="hstack" style={{ gap: 8 }}>
          <span className="badge badge-muted">{item.target_platform ?? item.type}</span>
          <span className="badge badge-success">ready to post</span>
        </div>
        <div className="hstack" style={{ gap: 8 }}>
          {item.source_confidence !== null && <LeadMatchBadge score={item.source_confidence} />}
          {item.source_buying_intent !== null && (
            <LeadIntentBadge intent={item.source_buying_intent} />
          )}
        </div>
      </div>

      <SourcePost item={item} />

      {item.source_pain_point && <WhyThisLead pain_point={item.source_pain_point} />}

      <div className="content-body">{item.body}</div>

      {error && <div className="error-banner">{error}</div>}

      <div className="hstack">
        <button type="button" onClick={handleCopy}>
          {copied ? "Copied!" : "Copy reply text"}
        </button>
        {postUrl && (
          <a href={postUrl} target="_blank" rel="noopener noreferrer" className="btn btn-secondary">
            Open original post ↗
          </a>
        )}
        <button type="button" className="btn-secondary" onClick={handleMarkPosted} disabled={busy}>
          I&apos;ve posted this
        </button>
        <button type="button" className="btn-danger" onClick={handleDiscard} disabled={busy}>
          Discard
        </button>
      </div>
    </div>
  );
}

// An approved item on a platform this system *does* auto-publish to, but the publish
// attempt failed (see backend/app/jobs/publish.py) — publish_error and the retry endpoint
// already existed, this is just the first UI that surfaces either. Without this, a failed
// publish was only ever visible via a Sentry alert, never in the product itself. Also lives
// on the Ready to Post page — same "approved but still needs something from you" bucket as
// ReadyToPostCard above, just a different reason it's not done yet.
export function NeedsAttentionCard({
  item,
  projectId,
  onResolved,
}: {
  item: ContentItem;
  projectId: string;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRetry() {
    setBusy(true);
    setError(null);
    try {
      await api.retryPublishContentItem(projectId, item.id);
      onResolved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not retry.");
      setBusy(false);
    }
  }

  async function handleDiscard() {
    setBusy(true);
    setError(null);
    try {
      await api.archiveContentItem(projectId, item.id, item.version, "Discarded, not retried.");
      onResolved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not discard.");
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="row">
        <span className="badge badge-muted">{item.target_platform ?? item.type}</span>
        <span className="badge badge-danger">failed to publish</span>
      </div>

      <div className="content-body">{item.body}</div>

      {item.publish_error && <div className="error-banner">{item.publish_error}</div>}
      {error && <div className="error-banner">{error}</div>}

      <div className="hstack">
        <button type="button" onClick={handleRetry} disabled={busy}>
          Retry publish
        </button>
        <button type="button" className="btn-danger" onClick={handleDiscard} disabled={busy}>
          Discard
        </button>
      </div>
    </div>
  );
}
