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

function PostedCard({
  item,
  selected,
  onToggleSelected,
  onDelete,
  deleting,
}: {
  item: ContentItem;
  selected: boolean;
  onToggleSelected: (id: string) => void;
  onDelete: (item: ContentItem) => void;
  deleting: boolean;
}) {
  const postUrl = originalPostUrl(item);

  return (
    <div className="card">
      <div className="row">
        <div className="hstack" style={{ alignItems: "center", gap: 10 }}>
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelected(item.id)}
            style={{ width: "auto" }}
            aria-label="Select this posted reply"
          />
          <span className="badge badge-muted">{item.target_platform ?? item.type}</span>
          <span className="muted">{formatDateTime(item.published_at)}</span>
        </div>
        <button
          type="button"
          className="btn-danger"
          style={{ padding: "2px 8px", fontSize: 12 }}
          onClick={() => onDelete(item)}
          disabled={deleting}
        >
          {deleting ? "Deleting..." : "Delete"}
        </button>
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
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

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

  // Selection can't survive a refresh meaningfully — items that were deleted are gone, and
  // holding stale ids around risks a bulk-delete retry against an id that's already archived.
  useEffect(() => {
    setSelectedIds(new Set());
  }, [postedItems]);

  function toggleSelected(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelectedIds((prev) =>
      prev.size === postedItems.length ? new Set() : new Set(postedItems.map((i) => i.id))
    );
  }

  async function deleteOne(item: ContentItem) {
    if (!project) return;
    setDeletingIds((prev) => new Set(prev).add(item.id));
    try {
      await api.archiveContentItem(project.id, item.id, item.version, "Removed from Posted tab.");
      await refresh();
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not delete this item.");
    } finally {
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(item.id);
        return next;
      });
    }
  }

  async function deleteSelected() {
    if (!project || selectedIds.size === 0) return;
    if (!window.confirm(`Delete ${selectedIds.size} posted repl${selectedIds.size === 1 ? "y" : "ies"}? This can't be undone.`)) {
      return;
    }
    setBulkDeleting(true);
    setLoadError(null);
    const targets = postedItems.filter((item) => selectedIds.has(item.id));
    const results = await Promise.allSettled(
      targets.map((item) =>
        api.archiveContentItem(project.id, item.id, item.version, "Removed from Posted tab.")
      )
    );
    const failures = results.filter((r) => r.status === "rejected").length;
    if (failures > 0) {
      setLoadError(
        `${failures} of ${targets.length} couldn't be deleted — they may have changed since this page loaded. Refresh and try again.`
      );
    }
    setBulkDeleting(false);
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
        <h1>Posted</h1>
        <p className="subtitle">Every reply you&apos;ve marked as posted, so you never lose track of where.</p>
        {loadError && <div className="error-banner">{loadError}</div>}

        {postedItems.length === 0 && !loadError && (
          <div className="empty-state">Nothing posted yet — approved replies show up here once you mark them posted.</div>
        )}

        {postedItems.length > 0 && (
          <div className="row" style={{ marginBottom: 12, alignItems: "center" }}>
            <label className="hstack muted" style={{ alignItems: "center", gap: 8, fontSize: 13 }}>
              <input
                type="checkbox"
                checked={selectedIds.size === postedItems.length}
                onChange={toggleSelectAll}
                style={{ width: "auto" }}
              />
              Select all
            </label>
            <button
              type="button"
              className="btn-danger"
              onClick={deleteSelected}
              disabled={selectedIds.size === 0 || bulkDeleting}
            >
              {bulkDeleting ? "Deleting..." : `Delete selected (${selectedIds.size})`}
            </button>
          </div>
        )}

        {postedItems.map((item) => (
          <PostedCard
            key={item.id}
            item={item}
            selected={selectedIds.has(item.id)}
            onToggleSelected={toggleSelected}
            onDelete={deleteOne}
            deleting={deletingIds.has(item.id)}
          />
        ))}
      </div>
    </>
  );
}
