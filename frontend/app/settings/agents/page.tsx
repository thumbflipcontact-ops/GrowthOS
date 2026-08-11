"use client";

import { useEffect, useState } from "react";
import { TopNav } from "@/components/TopNav";
import { ApiError, api } from "@/lib/api-client";
import type { AgentRun } from "@/lib/types";
import { useSession } from "@/lib/useSession";

const AGENT_KEY = "conversation_finder";
// Matches MINIMUM_SCHEDULE_INTERVAL_SECONDS in backend/app/services/agent_config.py — the
// platform-wide floor. Only option for now since nothing shorter is actually accepted.
const SCHEDULE_CRON = "0 */6 * * *";

function keywordsToText(keywords: unknown): string {
  return Array.isArray(keywords) ? keywords.join(", ") : "";
}

function textToKeywords(text: string): string[] {
  return text
    .split(",")
    .map((k) => k.trim())
    .filter(Boolean);
}

const PAGE_SIZE_OPTIONS = [20, 50, 100];

function AgentSettingsCard({ projectId }: { projectId: string }) {
  const [keywordsText, setKeywordsText] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function loadRuns(atPage = page, size = pageSize) {
    try {
      const res = await api.listAgentRuns(projectId, AGENT_KEY, {
        limit: size,
        offset: atPage * size,
      });
      setRuns(res.runs);
      setRunsTotal(res.total);
    } catch {
      // Non-fatal — the config form still works without run history.
    }
  }

  useEffect(() => {
    api
      .listAgentConfigs(projectId)
      .then((configs) => {
        const existing = configs.find((c) => c.agent_key === AGENT_KEY);
        if (existing) {
          setKeywordsText(keywordsToText(existing.config.keywords));
          setEnabled(existing.enabled);
        }
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load agent settings."))
      .finally(() => setLoading(false));
    loadRuns(0, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  function handlePageSizeChange(size: number) {
    setPageSize(size);
    setPage(0);
    loadRuns(0, size);
  }

  function handlePageChange(nextPage: number) {
    setPage(nextPage);
    loadRuns(nextPage, pageSize);
  }

  async function handleDeleteRun(runId: string) {
    if (!window.confirm("Delete this run? This can't be undone.")) return;
    setDeletingId(runId);
    try {
      await api.deleteAgentRun(projectId, AGENT_KEY, runId);
      // If deleting the last row on a page beyond the first, step back a page instead of
      // showing an empty page — same UX as most paginated tables.
      const isLastRowOnPage = runs.length === 1 && page > 0;
      const nextPage = isLastRowOnPage ? page - 1 : page;
      setPage(nextPage);
      await loadRuns(nextPage, pageSize);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete this run.");
    } finally {
      setDeletingId(null);
    }
  }

  async function saveConfig() {
    await api.upsertAgentConfig(projectId, AGENT_KEY, {
      config: { keywords: textToKeywords(keywordsText) },
      schedule_cron: SCHEDULE_CRON,
      enabled,
    });
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSavedMessage(null);
    setSaving(true);
    try {
      await saveConfig();
      setSavedMessage("Saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save agent settings.");
    } finally {
      setSaving(false);
    }
  }

  async function handleRunNow() {
    setError(null);
    setSavedMessage(null);
    setRunning(true);
    try {
      // Always save first — otherwise "Run now" silently runs against whatever config was
      // last saved (possibly empty keywords) rather than what's currently in the form, and
      // the mismatch is invisible: the run still "succeeds" with 0 results.
      await saveConfig();
      await api.triggerAgentRun(projectId, AGENT_KEY);
      setSavedMessage("Saved and run started — check back below in a moment.");
      setTimeout(loadRuns, 3000);
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) {
        setError("Your subscription isn't active — start or resume it from the dashboard first.");
      } else {
        setError(err instanceof ApiError ? err.message : "Could not start a run.");
      }
    } finally {
      setRunning(false);
    }
  }

  if (loading) return <div className="card muted">Loading...</div>;

  return (
    <div className="card">
      <h2>Conversation Finder</h2>
      <p className="muted">
        Searches your connected accounts for conversations matching these keywords, then drafts
        a reply for your approval. Runs automatically every 6 hours once enabled, or trigger a
        run right now to test it.
      </p>

      {error && <div className="error-banner">{error}</div>}
      {savedMessage && <p className="muted">{savedMessage}</p>}

      <form onSubmit={handleSave}>
        <label htmlFor="keywords">Keywords</label>
        <input
          id="keywords"
          value={keywordsText}
          onChange={(e) => setKeywordsText(e.target.value)}
          placeholder="e.g. crawl budget, technical SEO, site audit"
        />
        <p className="muted">Comma-separated. Threadly searches for posts matching any of these.</p>

        <label htmlFor="enabled" className="hstack" style={{ alignItems: "center", marginTop: 14 }}>
          <input
            id="enabled"
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            style={{ width: "auto" }}
          />
          <span>Run automatically every 6 hours</span>
        </label>

        <div className="hstack" style={{ marginTop: 20 }}>
          <button type="submit" disabled={saving}>
            {saving ? "Saving..." : "Save"}
          </button>
          <button type="button" className="btn-secondary" onClick={handleRunNow} disabled={running}>
            {running ? "Starting..." : "Run now"}
          </button>
        </div>
      </form>

      {runsTotal > 0 && (
        <>
          <h2 style={{ marginTop: 28 }}>Recent runs</h2>
          <div className="stack">
            {runs.map((run) => {
              const details = (run.summary?.details ?? {}) as {
                terms?: string[];
                platforms_searched?: string[];
                results_found?: number;
              };
              const knowledgeItemsCreated = run.summary?.knowledge_items_created as
                | number
                | undefined;
              // A run can "succeed" (no exception thrown) but still record a soft error, e.g.
              // no keywords configured — that never sets the top-level run.error field, only
              // this array, so it has to be checked separately or it's silently invisible.
              const softErrors = (run.summary?.errors ?? []) as string[];
              return (
                <div key={run.id} className="content-body" style={{ fontSize: 13, whiteSpace: "normal" }}>
                  <div className="row">
                    <span>{new Date(run.created_at).toLocaleString()}</span>
                    <div className="hstack" style={{ alignItems: "center", gap: 8 }}>
                      <span
                        className={`badge ${run.status === "failed" ? "badge-danger" : run.status === "succeeded" ? "badge-success" : "badge-muted"}`}
                      >
                        {run.status}
                      </span>
                      <button
                        type="button"
                        className="btn-danger"
                        style={{ padding: "2px 8px", fontSize: 12 }}
                        onClick={() => handleDeleteRun(run.id)}
                        disabled={deletingId === run.id}
                      >
                        {deletingId === run.id ? "Deleting..." : "Delete"}
                      </button>
                    </div>
                  </div>
                  {details.terms && details.terms.length > 0 && (
                    <p className="muted" style={{ margin: "6px 0 0" }}>
                      Searched for: {details.terms.join(", ")}
                    </p>
                  )}
                  {run.error && <p className="muted" style={{ margin: "6px 0 0" }}>{run.error}</p>}
                  {softErrors.map((msg, i) => (
                    <p key={i} className="error-banner" style={{ margin: "6px 0 0" }}>
                      {msg}
                    </p>
                  ))}
                  {run.status === "succeeded" && softErrors.length === 0 && (
                    <p className="muted" style={{ margin: "6px 0 0" }}>
                      Searched {details.platforms_searched?.join(", ") || "no connected platforms"} ·{" "}
                      {details.results_found ?? 0} raw result{details.results_found === 1 ? "" : "s"} ·{" "}
                      {knowledgeItemsCreated ?? 0} saved for drafting
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          <div className="row" style={{ marginTop: 16, alignItems: "center" }}>
            <div className="hstack" style={{ alignItems: "center", gap: 8 }}>
              <label htmlFor="page-size" className="muted" style={{ fontSize: 13 }}>
                Show
              </label>
              <select
                id="page-size"
                value={pageSize}
                onChange={(e) => handlePageSizeChange(Number(e.target.value))}
                style={{ width: "auto" }}
              >
                {PAGE_SIZE_OPTIONS.map((size) => (
                  <option key={size} value={size}>
                    {size}
                  </option>
                ))}
              </select>
              <span className="muted" style={{ fontSize: 13 }}>
                per page · {runsTotal} total
              </span>
            </div>
            <div className="hstack" style={{ gap: 8 }}>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => handlePageChange(page - 1)}
                disabled={page === 0}
              >
                Previous
              </button>
              <span className="muted" style={{ fontSize: 13, alignSelf: "center" }}>
                Page {page + 1} of {Math.max(1, Math.ceil(runsTotal / pageSize))}
              </span>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => handlePageChange(page + 1)}
                disabled={(page + 1) * pageSize >= runsTotal}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function AgentSettingsPage() {
  const { loading, organization, project, error } = useSession();

  if (loading) {
    return (
      <div className="container">
        <p className="muted">Loading...</p>
      </div>
    );
  }

  if (error || !organization || !project) {
    return (
      <div className="container">
        <div className="error-banner">{error ?? "Could not load your account."}</div>
      </div>
    );
  }

  return (
    <>
      <TopNav />
      <div className="container-wide">
        <h1>Agent settings</h1>
        <p className="subtitle">Tell Threadly what to look for.</p>
        <AgentSettingsCard projectId={project.id} />
      </div>
    </>
  );
}
