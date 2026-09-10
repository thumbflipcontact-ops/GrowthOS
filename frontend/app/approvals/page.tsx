"use client";

import { useCallback, useEffect, useState } from "react";
import {
  LeadIntentBadge,
  LeadMatchBadge,
  MANUAL_PUBLISH_ONLY_PLATFORMS,
  WhyThisLead,
} from "@/components/ApprovalCards";
import { SourcePost } from "@/components/SourcePost";
import { TopNav } from "@/components/TopNav";
import { ApiError, api } from "@/lib/api-client";
import { initPosthog } from "@/lib/posthog";
import type { ContentItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";

// The Approval Inbox is the highest-stakes surface in this app — it is the only UI that can
// approve or reject a content_item. Every interaction here biases toward making the human
// reviewer actually read what they're approving: one item, fully expanded, at a time.
// Deliberately no bulk-select-all APPROVE action, ever — see frontend/README.md and
// docs/api/API_DESIGN.md's "What's intentionally not in v1" (batch approval would weaken the
// human-review guarantee the whole system exists to provide). Bulk-select REJECT is fine —
// discarding a draft never publishes anything, so it doesn't carry that same risk.
function ApprovalCard({
  item,
  projectId,
  onResolved,
  selected,
  onToggleSelected,
}: {
  item: ContentItem;
  projectId: string;
  onResolved: () => void;
  selected: boolean;
  onToggleSelected: (id: string) => void;
}) {
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
      initPosthog()?.capture("draft_approved", { platform: item.target_platform ?? item.type });
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
        <div className="hstack" style={{ alignItems: "center", gap: 10 }}>
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelected(item.id)}
            style={{ width: "auto" }}
            aria-label="Select this draft"
          />
          <span className="badge badge-muted">{item.target_platform ?? item.type}</span>
        </div>
        <div className="hstack" style={{ gap: 8 }}>
          {item.source_confidence !== null && <LeadMatchBadge score={item.source_confidence} />}
          {item.source_buying_intent !== null && (
            <LeadIntentBadge intent={item.source_buying_intent} />
          )}
          <span className="muted" style={{ fontSize: 13 }}>
            Draft quality: {Number(item.confidence).toFixed(2)}
          </span>
        </div>
      </div>

      <SourcePost item={item} />

      {item.source_pain_point && <WhyThisLead pain_point={item.source_pain_point} />}

      <div className="content-body">{item.body}</div>

      {manualPublishOnly && (
        <p className="muted" style={{ fontSize: 13 }}>
          Threadly can&apos;t post this one automatically — approving moves it to the{" "}
          <a href="/ready-to-post">Ready to Post</a> tab, where you can copy it and post it
          yourself.
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

export default function ApprovalsPage() {
  const { loading, project, error: sessionError } = useSession();
  const [pendingItems, setPendingItems] = useState<ContentItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedPendingIds, setSelectedPendingIds] = useState<Set<string>>(new Set());
  const [bulkRejecting, setBulkRejecting] = useState(false);

  const refresh = useCallback(async () => {
    if (!project) return;
    try {
      const pending = await api.listContentItems(project.id, "pending_review");
      setPendingItems(pending);
      setSelectedPendingIds(new Set()); // a fetched list never matches a stale selection
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load drafts.");
    }
  }, [project]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function toggleSelected(id: string) {
    setSelectedPendingIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelectedPendingIds((prev) =>
      prev.size === pendingItems.length ? new Set() : new Set(pendingItems.map((i) => i.id))
    );
  }

  async function handleBulkReject() {
    if (!project || selectedPendingIds.size === 0) return;
    const reason = window.prompt(
      `Why are you rejecting ${selectedPendingIds.size} draft${selectedPendingIds.size === 1 ? "" : "s"}? This reason is applied to all of them.`
    );
    if (!reason || !reason.trim()) return; // cancelled, or left blank — reason is required
    setBulkRejecting(true);
    setLoadError(null);
    const targets = pendingItems.filter((item) => selectedPendingIds.has(item.id));
    const results = await Promise.allSettled(
      targets.map((item) => api.rejectContentItem(project.id, item.id, item.version, reason.trim()))
    );
    const failures = results.filter((r) => r.status === "rejected").length;
    if (failures > 0) {
      setLoadError(
        `${failures} of ${targets.length} couldn't be rejected — they may have changed since this page loaded. Refresh and try again.`
      );
    }
    setBulkRejecting(false);
    await refresh();
  }

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

        {pendingItems.length === 0 && !loadError && (
          <div className="empty-state">Nothing waiting for review right now.</div>
        )}

        {pendingItems.length > 0 && (
          <div className="row" style={{ marginBottom: 12, alignItems: "center" }}>
            <label className="hstack muted" style={{ alignItems: "center", gap: 8, fontSize: 13 }}>
              <input
                type="checkbox"
                checked={selectedPendingIds.size === pendingItems.length}
                onChange={toggleSelectAll}
                style={{ width: "auto" }}
              />
              Select all
            </label>
            <button
              type="button"
              className="btn-danger"
              onClick={handleBulkReject}
              disabled={selectedPendingIds.size === 0 || bulkRejecting}
            >
              {bulkRejecting ? "Rejecting..." : `Reject selected (${selectedPendingIds.size})`}
            </button>
          </div>
        )}

        {pendingItems.map((item) => (
          <ApprovalCard
            key={item.id}
            item={item}
            projectId={project.id}
            onResolved={refresh}
            selected={selectedPendingIds.has(item.id)}
            onToggleSelected={toggleSelected}
          />
        ))}
      </div>
    </>
  );
}
