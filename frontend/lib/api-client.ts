// Typed client for backend/app/api/v1 — see docs/api/API_DESIGN.md's error envelope.
//
// credentials: 'include' on every call is load-bearing: the session cookie
// (backend/app/core/security.py) is httpOnly, set by the backend on /auth/login and
// /auth/register, and must be sent on every subsequent request. Frontend and backend must
// share a registrable domain (subdomains are fine) for this to work — see
// backend/app/core/config.py's frontend_origin docstring.

import type {
  AgentConfig,
  AgentRun,
  AgentTriggerResponse,
  ApiErrorBody,
  CheckoutSessionResponse,
  ContentItem,
  OAuthStartResponse,
  Organization,
  PluginCatalogEntry,
  PluginConnection,
  PortalSessionResponse,
  Project,
  SubscriptionStatus,
  User,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.code = body.error.code;
    this.status = status;
    this.details = body.error.details;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let body: ApiErrorBody;
    try {
      body = await response.json();
    } catch {
      body = { error: { code: "unknown_error", message: response.statusText, details: {} } };
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json();
}

export const api = {
  register(body: {
    org_name: string;
    org_slug: string;
    email: string;
    name: string;
    password: string;
  }): Promise<User> {
    return apiFetch("/api/v1/auth/register", { method: "POST", body: JSON.stringify(body) });
  },

  login(body: { email: string; password: string }): Promise<User> {
    return apiFetch("/api/v1/auth/login", { method: "POST", body: JSON.stringify(body) });
  },

  logout(): Promise<void> {
    return apiFetch("/api/v1/auth/logout", { method: "POST" });
  },

  me(): Promise<User> {
    return apiFetch("/api/v1/auth/me");
  },

  myOrganizations(): Promise<Organization[]> {
    return apiFetch("/api/v1/auth/me/organizations");
  },

  listProjects(orgId: string): Promise<Project[]> {
    return apiFetch(`/api/v1/orgs/${orgId}/projects`);
  },

  createProject(orgId: string, body: { name: string; slug: string }): Promise<Project> {
    return apiFetch(`/api/v1/orgs/${orgId}/projects`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  createCheckoutSession(orgId: string): Promise<CheckoutSessionResponse> {
    return apiFetch(`/api/v1/orgs/${orgId}/billing/checkout-session`, { method: "POST" });
  },

  createPortalSession(orgId: string): Promise<PortalSessionResponse> {
    return apiFetch(`/api/v1/orgs/${orgId}/billing/portal-session`, { method: "POST" });
  },

  getSubscriptionStatus(orgId: string): Promise<SubscriptionStatus> {
    return apiFetch(`/api/v1/orgs/${orgId}/billing/status`);
  },

  pluginCatalog(): Promise<PluginCatalogEntry[]> {
    return apiFetch("/api/v1/plugins/catalog");
  },

  listPluginConnections(projectId: string): Promise<PluginConnection[]> {
    return apiFetch(`/api/v1/projects/${projectId}/plugin-connections`);
  },

  createPluginConnection(
    projectId: string,
    body: { plugin_key: string; config: Record<string, unknown>; capabilities_enabled: string[] }
  ): Promise<PluginConnection> {
    return apiFetch(`/api/v1/projects/${projectId}/plugin-connections`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  startOAuthConnection(projectId: string, pluginKey: string): Promise<OAuthStartResponse> {
    return apiFetch(`/api/v1/projects/${projectId}/plugin-connections/${pluginKey}/oauth/start`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  disconnectOAuthConnection(projectId: string, connectionId: string): Promise<void> {
    return apiFetch(
      `/api/v1/projects/${projectId}/plugin-connections/${connectionId}/oauth/disconnect`,
      { method: "POST" }
    );
  },

  listContentItems(projectId: string, status?: string): Promise<ContentItem[]> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return apiFetch(`/api/v1/projects/${projectId}/content-items${query}`);
  },

  approveContentItem(projectId: string, itemId: string, version: number): Promise<ContentItem> {
    return apiFetch(`/api/v1/projects/${projectId}/content-items/${itemId}/approve`, {
      method: "POST",
      body: JSON.stringify({ version }),
    });
  },

  rejectContentItem(
    projectId: string,
    itemId: string,
    version: number,
    reason: string
  ): Promise<ContentItem> {
    return apiFetch(`/api/v1/projects/${projectId}/content-items/${itemId}/reject`, {
      method: "POST",
      body: JSON.stringify({ version, reason }),
    });
  },

  archiveContentItem(
    projectId: string,
    itemId: string,
    version: number,
    reason?: string
  ): Promise<ContentItem> {
    return apiFetch(`/api/v1/projects/${projectId}/content-items/${itemId}/archive`, {
      method: "POST",
      body: JSON.stringify(reason ? { version, reason } : { version }),
    });
  },

  markContentItemPublished(
    projectId: string,
    itemId: string,
    version: number
  ): Promise<ContentItem> {
    return apiFetch(`/api/v1/projects/${projectId}/content-items/${itemId}/mark-published`, {
      method: "POST",
      body: JSON.stringify({ version }),
    });
  },

  retryPublishContentItem(projectId: string, itemId: string): Promise<ContentItem> {
    return apiFetch(`/api/v1/projects/${projectId}/content-items/${itemId}/retry-publish`, {
      method: "POST",
    });
  },

  listAgentConfigs(projectId: string): Promise<AgentConfig[]> {
    return apiFetch(`/api/v1/projects/${projectId}/agent-configs`);
  },

  upsertAgentConfig(
    projectId: string,
    agentKey: string,
    body: { config: Record<string, unknown>; schedule_cron: string | null; enabled: boolean }
  ): Promise<AgentConfig> {
    return apiFetch(`/api/v1/projects/${projectId}/agent-configs/${agentKey}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  },

  triggerAgentRun(projectId: string, agentKey: string): Promise<AgentTriggerResponse> {
    return apiFetch(`/api/v1/projects/${projectId}/agent-configs/${agentKey}/runs/trigger`, {
      method: "POST",
    });
  },

  listAgentRuns(projectId: string, agentKey: string): Promise<AgentRun[]> {
    return apiFetch(`/api/v1/projects/${projectId}/agent-configs/${agentKey}/runs`);
  },
};
