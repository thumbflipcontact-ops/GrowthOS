"use client";

import { useCallback, useEffect, useState } from "react";
import { TopNav } from "@/components/TopNav";
import { ApiError, api } from "@/lib/api-client";
import { initPosthog } from "@/lib/posthog";
import type { PluginCatalogEntry, PluginConnection } from "@/lib/types";
import { useSession } from "@/lib/useSession";

const STATUS_BADGE: Record<string, string> = {
  connected: "badge-success",
  disconnected: "badge-muted",
  error: "badge-danger",
  expired: "badge-warn",
};

const PLUGIN_LABELS: Record<string, string> = {
  twitter: "X (Twitter)",
  reddit: "Reddit",
};

// LinkedIn's own API has no third-party post-search access at any tier — Threadly only
// supports platforms it can actually discover conversations on. Reddit's OAuth app was never
// finished being set up (its OAuth client credentials aren't configured on the backend), and
// testing it requires a working, non-banned Reddit account this project doesn't currently
// have — so for now Threadly only supports X. Neither plugin package is deleted (see
// plugins/linkedin/, plugins/reddit/), both are just kept out of every customer-facing
// surface until they're actually ready.
const UNSUPPORTED_PLUGIN_KEYS = new Set(["linkedin", "reddit"]);

function PluginRow({
  entry,
  connection,
  projectId,
  onChanged,
}: {
  entry: PluginCatalogEntry;
  connection: PluginConnection | undefined;
  projectId: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const label = PLUGIN_LABELS[entry.plugin_key] ?? entry.plugin_key;

  async function handleConnect() {
    setBusy(true);
    setError(null);
    try {
      if (!connection) {
        await api.createPluginConnection(projectId, {
          plugin_key: entry.plugin_key,
          config: {},
          capabilities_enabled: entry.capabilities,
        });
      }
      const { authorize_url } = await api.startOAuthConnection(projectId, entry.plugin_key);
      initPosthog()?.capture("plugin_connect_clicked", { plugin_key: entry.plugin_key });
      window.location.href = authorize_url;
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) {
        setError("Your subscription isn't active — start or resume it from the dashboard first.");
      } else {
        setError(err instanceof ApiError ? err.message : "Could not start connection.");
      }
      setBusy(false);
    }
  }

  async function handleDisconnect() {
    if (!connection) return;
    setBusy(true);
    setError(null);
    try {
      await api.disconnectOAuthConnection(projectId, connection.id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not disconnect.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="row">
        <div>
          <h2 style={{ margin: 0 }}>{label}</h2>
          {connection ? (
            <span className={`badge ${STATUS_BADGE[connection.status] ?? "badge-muted"}`}>
              {connection.status}
            </span>
          ) : (
            <span className="badge badge-muted">not connected</span>
          )}
        </div>
        <div className="hstack">
          {connection && connection.status === "connected" ? (
            <button type="button" className="btn-danger" onClick={handleDisconnect} disabled={busy}>
              Disconnect
            </button>
          ) : (
            <button type="button" onClick={handleConnect} disabled={busy}>
              {connection ? "Reconnect" : "Connect"}
            </button>
          )}
        </div>
      </div>
      {error && <p className="error-banner">{error}</p>}
    </div>
  );
}

export default function PluginsPage() {
  const { loading, project, error: sessionError } = useSession();
  const [catalog, setCatalog] = useState<PluginCatalogEntry[]>([]);
  const [connections, setConnections] = useState<PluginConnection[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!project) return;
    try {
      const [catalogRes, connectionsRes] = await Promise.all([
        api.pluginCatalog(),
        api.listPluginConnections(project.id),
      ]);
      // Only plugins with a real, connectable OAuth flow — this UI has no form for api_key/
      // session_credentials auth types yet (e.g. the "dummy" test fixture) — and only
      // platforms Threadly actually supports discovery on (see UNSUPPORTED_PLUGIN_KEYS).
      setCatalog(
        catalogRes.filter(
          (entry) => entry.auth_type === "oauth2" && !UNSUPPORTED_PLUGIN_KEYS.has(entry.plugin_key)
        )
      );
      setConnections(connectionsRes);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load connections.");
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
        <h1>Connections</h1>
        <p className="subtitle">
          Connect the accounts Threadly should monitor and post to. Every reply is drafted for
          review — nothing posts without your approval.
        </p>
        {loadError && <div className="error-banner">{loadError}</div>}
        {catalog.length === 0 && !loadError && (
          <p className="muted">No connectable plugins are installed on this deployment.</p>
        )}
        {catalog.map((entry) => (
          <PluginRow
            key={entry.plugin_key}
            entry={entry}
            connection={connections.find((c) => c.plugin_key === entry.plugin_key)}
            projectId={project.id}
            onChanged={refresh}
          />
        ))}
      </div>
    </>
  );
}
