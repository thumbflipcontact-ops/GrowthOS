"use client";

import { useCallback, useEffect, useState } from "react";
import { SourcePost, originalPostUrl } from "@/components/SourcePost";
import { TopNav } from "@/components/TopNav";
import { ApiError, api } from "@/lib/api-client";
import type { ContentItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";

function formatDateTime(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function PostedCard({ item }: { item: ContentItem }) {
  const postUrl = originalPostUrl(item);

  return (
    <div className="card">
      <div className="row">
        <span className="badge badge-muted">{item.target_platform ?? item.type}</span>
        <span className="muted">{formatDateTime(item.published_at)}</span>
      </div>

      <SourcePost item={item} />

      <div className="content-body">
        <strong>What you posted:</strong>
        <div style={{ marginTop: 4, whiteSpace: "pre-wrap" }}>{item.body}</div>
      </div>

      {postUrl && (
        <div className="hstack">
          <a href={postUrl} target="_blank" rel="noopener noreferrer" className="btn-secondary">
            View post on X ↗
          </a>
        </div>
      )}
    </div>
  );
}

export default function PostedPage() {
  const { loading, project, error: sessionError } = useSession();
  const [postedItems, setPostedItems] = useState<ContentItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!project) return;
    try {
      const items = await api.listContentItems(project.id, "published");
      // Most recently posted first — the whole point is "where did I already comment",
      // and recent activity is what you're most likely trying to recall.
      setPostedItems(
        [...items].sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""))
      );
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load posted items.");
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
        <h1>Posted</h1>
        <p className="subtitle">Every reply you&apos;ve marked as posted, so you never lose track of where.</p>
        {loadError && <div className="error-banner">{loadError}</div>}

        {postedItems.length === 0 && !loadError && (
          <div className="empty-state">Nothing posted yet — approved replies show up here once you mark them posted.</div>
        )}

        {postedItems.map((item) => (
          <PostedCard key={item.id} item={item} />
        ))}
      </div>
    </>
  );
}
