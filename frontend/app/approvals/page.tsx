"use client";

import { useCallback, useEffect, useState } from "react";
import { SourcePost, originalPostUrl } from "@/components/SourcePost";
import { TopNav } from "@/components/TopNav";
import { ApiError, api } from "@/lib/api-client";
import type { ContentItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";

// X's own platform policy (Feb 2026) blocks a programmatic reply/quote unless the target
// post's author already @mentioned this account or quoted it first — every organically
// discovered post fails that by construction, so the backend never even attempts to
// auto-publish a twitter item (see backend/app/api/v1/content_items.py's
// _MANUAL_PUBLISH_ONLY_PLATFORMS). This is the frontend's matching list: which platforms an
// approved item needs a human to post themselves, rather than waiting on a publish job.
const MANUAL_PUBLISH_ONLY_PLATFORMS = new Set(["twitter"]);

// The Approval Inbox is the highest-stakes surface in this app — it is the only UI that can
// approve or reject a content_item. Every interaction here biases toward making the human
// reviewer actually read what they're approving: one item, fully expanded, at a time.
// Deliberately no "approve all" / bulk-select action — see frontend/README.md.
function ApprovalCard({ item, projectId, onResolved }: { item: ContentItem; projectId: string; onResolved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRejectReason, setShowRejectReason] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const manualPublishOnly = item.target_platform
    ? MANUAL_PUBLISH_ONLY_PLATFORMS.has(item.target_platform)
    : false;

  async function handleApprove() {
    setBusy(true);
    setError(null);
    try {
      await api.approveContentItem(projectId, item.id, item.version);
      onResolved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not approve.");
      setBusy(false);
    }
  }

  async function handleReject() {
    if (!rejectReason.trim()) {
      setError("A reason is required to reject.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.rejectContentItem(projectId, item.id, item.version, rejectReason.trim());
      onResolved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reject.");
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="row">
        <span className="badge badge-muted">{item.target_platform ?? item.type}</span>
        <span className="muted">confidence: {Number(item.confidence).toFixed(2)}</span>
      </div>

      <SourcePost item={item} />

      <div className="content-body">{item.body}</div>

      {item.reasoning && (
        <p className="muted">
          <strong>Agent&apos;s reasoning:</strong> {item.reasoning}
        </p>
      )}

      {manualPublishOnly && (
        <p className="muted" style={{ fontSize: 13 }}>
          X doesn&apos;t allow posting this automatically — approving moves it to
          &ldquo;Ready to post&rdquo; below, where you can copy it and post it yourself.
        </p>
      )}

      {error && <div className="error-banner">{error}</div>}

      {showRejectReason ? (
        <div className="stack">
          <label htmlFor={`reason-${item.id}`}>Why are you rejecting this?</label>
          <input
            id={`reason-${item.id}`}
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder="e.g. tone is off, not relevant, factually incorrect"
          />
          <div className="hstack">
            <button type="button" className="btn-danger" onClick={handleReject} disabled={busy}>
              Confirm reject
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setShowRejectReason(false)}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="hstack">
          <button type="button" onClick={handleApprove} disabled={busy}>
            {manualPublishOnly ? "Approve" : "Approve & publish"}
          </button>
          <button
            type="button"
            className="btn-danger"
            onClick={() => setShowRejectReason(true)}
            disabled={busy}
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}

// An approved item whose platform this system can't auto-publish to (see
// MANUAL_PUBLISH_ONLY_PLATFORMS) — copy the text, open the original post, post it yourself,
// then confirm it here so it stops showing up as waiting on you.
function ReadyToPostCard({ item, projectId, onResolved }: { item: ContentItem; projectId: string; onResolved: () => void }) {
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
        <span className="badge badge-muted">{item.target_platform ?? item.type}</span>
        <span className="badge badge-success">ready to post</span>
      </div>

      <SourcePost item={item} />

      <div className="content-body">{item.body}</div>

      {error && <div className="error-banner">{error}</div>}

      <div className="hstack">
        <button type="button" onClick={handleCopy}>
          {copied ? "Copied!" : "Copy reply text"}
        </button>
        {postUrl && (
          <a href={postUrl} target="_blank" rel="noopener noreferrer" className="btn btn-secondary">
            Open post on X ↗
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
// publish was only ever visible via a Sentry alert, never in the product itself.
function NeedsAttentionCard({ item, projectId, onResolved }: { item: ContentItem; projectId: string; onResolved: () => void }) {
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

export default function ApprovalsPage() {
  const { loading, project, error: sessionError } = useSession();
  const [pendingItems, setPendingItems] = useState<ContentItem[]>([]);
  const [approvedItems, setApprovedItems] = useState<ContentItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!project) return;
    try {
      const [pending, approved] = await Promise.all([
        api.listContentItems(project.id, "pending_review"),
        api.listContentItems(project.id, "approved"),
      ]);
      setPendingItems(pending);
      setApprovedItems(approved);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load drafts.");
    }
  }, [project]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (loading) {
    return (
      <div className="container">
        <p className="muted">Loading...</p>
      </div>
    );
  }

  if (sessionError || !project) {
    return (
      <div className="container">
        <div className="error-banner">{sessionError ?? "Could not load your account."}</div>
      </div>
    );
  }

  const readyToPost = approvedItems.filter(
    (item) => item.target_platform && MANUAL_PUBLISH_ONLY_PLATFORMS.has(item.target_platform)
  );
  const needsAttention = approvedItems.filter(
    (item) =>
      !(item.target_platform && MANUAL_PUBLISH_ONLY_PLATFORMS.has(item.target_platform)) &&
      item.publish_error
  );

  return (
    <>
      <TopNav />
      <div className="container-wide">
        <h1>Approvals</h1>
        <p className="subtitle">Read each draft before approving — nothing posts automatically.</p>
        {loadError && <div className="error-banner">{loadError}</div>}

        {pendingItems.length === 0 && needsAttention.length === 0 && readyToPost.length === 0 && !loadError && (
          <div className="empty-state">Nothing waiting for review right now.</div>
        )}

        {pendingItems.map((item) => (
          <ApprovalCard key={item.id} item={item} projectId={project.id} onResolved={refresh} />
        ))}

        {needsAttention.length > 0 && (
          <>
            <h2 style={{ marginTop: 28 }}>Needs attention</h2>
            {needsAttention.map((item) => (
              <NeedsAttentionCard key={item.id} item={item} projectId={project.id} onResolved={refresh} />
            ))}
          </>
        )}

        {readyToPost.length > 0 && (
          <>
            <h2 style={{ marginTop: 28 }}>Ready to post</h2>
            {readyToPost.map((item) => (
              <ReadyToPostCard key={item.id} item={item} projectId={project.id} onResolved={refresh} />
            ))}
          </>
        )}
      </div>
    </>
  );
}
