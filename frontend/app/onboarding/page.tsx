"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { useSession } from "@/lib/useSession";

// Matches MINIMUM_SCHEDULE_INTERVAL_SECONDS in backend/app/services/agent_config.py — the
// platform-wide floor, same constant frontend/app/settings/agents/page.tsx uses.
const SCHEDULE_CRON = "0 */6 * * *";

function textToKeywords(text: string): string[] {
  return text
    .split(",")
    .map((k) => k.trim())
    .filter(Boolean);
}

function OnboardingForm({ projectId }: { projectId: string }) {
  const [suggestUrl, setSuggestUrl] = useState("");
  const [keywordsText, setKeywordsText] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSuggest(e: React.FormEvent) {
    e.preventDefault();
    if (!suggestUrl.trim()) return;
    setError(null);
    setSuggesting(true);
    try {
      const { keywords } = await api.suggestKeywords(projectId, suggestUrl.trim());
      // Merge, never replace — if someone typed something first, don't destroy it.
      const existing = textToKeywords(keywordsText);
      const merged = [...existing, ...keywords.filter((k) => !existing.includes(k))];
      setKeywordsText(merged.join(", "));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not read that website. Try a different URL."
      );
    } finally {
      setSuggesting(false);
    }
  }

  async function handleStart(e: React.FormEvent) {
    e.preventDefault();
    const keywords = textToKeywords(keywordsText);
    if (keywords.length === 0) {
      setError("Add at least one keyword first — type your own or suggest some from your website.");
      return;
    }
    setError(null);
    setStarting(true);
    try {
      await api.upsertAgentConfig(projectId, "conversation_finder", {
        config: { keywords },
        schedule_cron: SCHEDULE_CRON,
        enabled: true,
      });
      // Kick off a real search immediately — the first drafts should be waiting soon, not up
      // to 6 hours from now.
      await api.triggerAgentRun(projectId, "conversation_finder");
      window.location.href = "/dashboard";
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your keywords.");
      setStarting(false);
    }
  }

  return (
    <>
      {error && <div className="error-banner">{error}</div>}

      <form onSubmit={handleSuggest}>
        <label htmlFor="suggest-url">Your website</label>
        <input
          id="suggest-url"
          type="url"
          value={suggestUrl}
          onChange={(e) => setSuggestUrl(e.target.value)}
          placeholder="https://yourproduct.com"
        />
        <button type="submit" className="btn-secondary" disabled={suggesting || !suggestUrl.trim()}>
          {suggesting ? "Reading your site..." : "Suggest keywords"}
        </button>
      </form>

      <form onSubmit={handleStart} style={{ marginTop: 20 }}>
        <label htmlFor="keywords">Keywords</label>
        <input
          id="keywords"
          value={keywordsText}
          onChange={(e) => setKeywordsText(e.target.value)}
          placeholder="e.g. crawl budget, technical SEO, site audit"
        />
        <p className="muted">
          Comma-separated. Threadly searches Reddit for posts matching any of these — edit
          them however you like before starting.
        </p>
        <button type="submit" className="btn-block" disabled={starting}>
          {starting ? "Starting..." : "Start finding leads"}
        </button>
      </form>

      <p className="muted" style={{ marginTop: 16, textAlign: "center" }}>
        <a href="/dashboard">Skip for now</a>
      </p>
    </>
  );
}

export default function OnboardingPage() {
  const { loading, project, error } = useSession();

  if (loading) {
    return (
      <div className="container">
        <p className="muted">Loading...</p>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="container">
        <div className="error-banner">{error ?? "Could not load your account."}</div>
      </div>
    );
  }

  return (
    <div className="container">
      <h1>Let&apos;s find your first leads</h1>
      <p className="subtitle">
        No Reddit login needed — just tell Threadly what to look for.
      </p>
      <div className="card">
        <OnboardingForm projectId={project.id} />
      </div>
    </div>
  );
}
