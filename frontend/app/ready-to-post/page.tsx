"use client";

import { useCallback, useEffect, useState } from "react";
import {
  MANUAL_PUBLISH_ONLY_PLATFORMS,
  NeedsAttentionCard,
  ReadyToPostCard,
} from "@/components/ApprovalCards";
import { TopNav } from "@/components/TopNav";
import { ApiError, api } from "@/lib/api-client";
import type { ContentItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";

// Approved items that still need something from you before they're actually posted — split
// out of the Approvals page (which used to stack this below the pending-review queue,
// requiring a scroll past everything already decided) so "decide on a draft" and "go post an
// approved one" are two separate places instead of one long page.
export default function ReadyToPostPage() {
  const { loading, project, error: sessionError } = useSession();
  const [approvedItems, setApprovedItems] = useState<ContentItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!project) return;
    try {
      const approved = await api.listContentItems(project.id, "approved");
      setApprovedItems(approved);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load approved drafts.");
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
        <h1>Ready to Post</h1>
        <p className="subtitle">
          You&apos;ve approved these — copy the reply, post it yourself, then mark it posted.
        </p>
        {loadError && <div className="error-banner">{loadError}</div>}

        {readyToPost.length === 0 && needsAttention.length === 0 && !loadError && (
          <div className="empty-state">
            Nothing waiting to be posted right now — approved drafts show up here.
          </div>
        )}

        {needsAttention.length > 0 && (
          <>
            <h2 style={{ marginTop: needsAttention.length ? 0 : 28 }}>Needs attention</h2>
            {needsAttention.map((item) => (
              <NeedsAttentionCard key={item.id} item={item} projectId={project.id} onResolved={refresh} />
            ))}
          </>
        )}

        {readyToPost.map((item) => (
          <ReadyToPostCard key={item.id} item={item} projectId={project.id} onResolved={refresh} />
        ))}
      </div>
    </>
  );
}
