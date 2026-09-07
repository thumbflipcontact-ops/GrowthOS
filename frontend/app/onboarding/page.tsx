"use client";

import { useRef, useState } from "react";
import { KeywordChips } from "@/components/KeywordChips";
import { ApiError, api } from "@/lib/api-client";
import { useSession } from "@/lib/useSession";

// Matches MINIMUM_SCHEDULE_INTERVAL_SECONDS in backend/app/services/agent_config.py — the
// platform-wide floor, same constant frontend/app/settings/agents/page.tsx uses.
const SCHEDULE_CRON = "0 */6 * * *";

// How long to keep polling for the triggered run to finish before giving up and moving on
// anyway — a stuck worker shouldn't strand someone on this screen forever.
const POLL_TIMEOUT_MS = 60_000;
const POLL_INTERVAL_MS = 2_000;
// The search itself has no per-keyword progress to report — this just fills toward "nearly
// done" over roughly the length of a typical run, then snaps to 100% once it actually
// finishes (see finishScan below), same illusion MentionCatch's own equivalent screen gives.
const FAKE_PROGRESS_STEP = 4;
const FAKE_PROGRESS_INTERVAL_MS = 700;
const FAKE_PROGRESS_CAP = 90;

function ScanningScreen({ keywordCount, progress }: { keywordCount: number; progress: number }) {
  return (
    <div className="scan-screen">
      <div className="scan-icon">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#1e6b3a" strokeWidth="2">
          <circle cx="12" cy="12" r="9" />
          <circle cx="12" cy="12" r="1.5" fill="#1e6b3a" />
        </svg>
      </div>
      <div className="scan-label">Monitoring active</div>
      <h2 style={{ margin: 0 }}>Scanning Reddit for leads...</h2>
      <p className="muted" style={{ marginTop: 8 }}>
        Checking all of Reddit against {keywordCount} keyword{keywordCount === 1 ? "" : "s"}.
        Leads appear automatically.
      </p>
      <div className="scan-bar-track">
        <div className="scan-bar-fill" style={{ width: `${progress}%` }} />
      </div>
    </div>
  );
}

function OnboardingForm({ projectId }: { projectId: string }) {
  const [suggestUrl, setSuggestUrl] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState(0);
  const progressTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  async function handleSuggest(e: React.FormEvent) {
    e.preventDefault();
    if (!suggestUrl.trim()) return;
    setError(null);
    setSuggesting(true);
    try {
      const { keywords: suggested } = await api.suggestKeywords(projectId, suggestUrl.trim());
      // Replaces, not merges — see the identical note in settings/agents/page.tsx.
      setKeywords(suggested);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not read that website. Try a different URL."
      );
    } finally {
      setSuggesting(false);
    }
  }

  function finishScan() {
    if (progressTimer.current) clearInterval(progressTimer.current);
    setProgress(100);
    // Let the bar visibly reach the end before leaving, instead of jump-cutting away the
    // instant the real run resolves.
    setTimeout(() => {
      window.location.href = "/dashboard";
    }, 500);
  }

  async function pollUntilDone(triggeredAt: number) {
    progressTimer.current = setInterval(() => {
      setProgress((p) => Math.min(p + FAKE_PROGRESS_STEP, FAKE_PROGRESS_CAP));
    }, FAKE_PROGRESS_INTERVAL_MS);

    const deadline = triggeredAt + POLL_TIMEOUT_MS;
    while (Date.now() < deadline) {
      try {
        const { runs } = await api.listAgentRuns(projectId, "conversation_finder", {
          limit: 5,
          offset: 0,
        });
        const freshRun = runs.find((r) => new Date(r.created_at).getTime() >= triggeredAt - 2000);
        if (freshRun && (freshRun.status === "succeeded" || freshRun.status === "failed")) {
          break;
        }
      } catch {
        // Transient error — keep polling rather than stranding the user here.
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
    finishScan();
  }

  async function handleStart(e: React.FormEvent) {
    e.preventDefault();
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
      setScanning(true);
      pollUntilDone(Date.now());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your keywords.");
      setStarting(false);
    }
  }

  if (scanning) {
    return <ScanningScreen keywordCount={keywords.length} progress={progress} />;
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
        <KeywordChips
          id="keywords"
          keywords={keywords}
          onChange={setKeywords}
          placeholder="Type a keyword and press Enter"
        />
        <p className="muted">
          Threadly searches Reddit for posts matching any of these — remove one, add your
          own, edit however you like before starting.
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
