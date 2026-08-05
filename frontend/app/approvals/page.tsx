"use client";

import { useCallback, useEffect, useState } from "react";
import { TopNav } from "@/components/TopNav";
import { ApiError, api } from "@/lib/api-client";
import type { ContentItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";

// The Approval Inbox is the highest-stakes surface in this app — it is the only UI that can
// approve or reject a content_item. Every interaction here biases toward making the human
// reviewer actually read what they're approving: one item, fully expanded, at a time.
// Deliberately no "approve all" / bulk-select action — see frontend/README.md.
function ApprovalCard({ item, projectId, onResolved }: { item: ContentItem; projectId: string; onResolved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRejectReason, setShowRejectReason] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

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

      <div className="content-body">{item.body}</div>

      {item.reasoning && (
        <p className="muted">
          <strong>Agent&apos;s reasoning:</strong> {item.reasoning}
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
            placeholder="e.g. tone is off, wrong subreddit, factually incorrect"
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
            Approve & publish
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

export default function ApprovalsPage() {
  const { loading, project, error: sessionError } = useSession();
  const [items, setItems] = useState<ContentItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!project) return;
    try {
      const res = await api.listContentItems(project.id, "pending_review");
      setItems(res);
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

  return (
    <>
      <TopNav />
      <div className="container-wide">
        <h1>Approvals</h1>
        <p className="subtitle">Read each draft before approving — nothing posts automatically.</p>
        {loadError && <div className="error-banner">{loadError}</div>}
        {items.length === 0 && !loadError && (
          <div className="empty-state">Nothing waiting for review right now.</div>
        )}
        {items.map((item) => (
          <ApprovalCard key={item.id} item={item} projectId={project.id} onResolved={refresh} />
        ))}
      </div>
    </>
  );
}
