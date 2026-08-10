// Mirrors backend/app/schemas/*.py — kept in sync by hand (no shared codegen yet). Field
// names/types must match the Pydantic response_models exactly.

export interface User {
  id: string;
  email: string;
  name: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
}

export interface Project {
  id: string;
  org_id: string;
  name: string;
  slug: string;
  status: string;
  icp_config: Record<string, unknown>;
  brand_voice: Record<string, unknown>;
}

export interface PluginCatalogEntry {
  plugin_key: string;
  interface_version: string;
  capabilities: string[];
  content_types: Record<string, unknown>[];
  config_schema: Record<string, unknown>;
  auth_type: string;
}

export interface PluginConnection {
  id: string;
  project_id: string;
  plugin_key: string;
  label: string;
  capabilities_enabled: string[];
  config: Record<string, unknown>;
  status: string;
  last_checked_at: string | null;
  token_expires_at: string | null;
  granted_scopes: string[];
  created_at: string;
  updated_at: string;
}

export interface ContentItem {
  id: string;
  project_id: string;
  type: string;
  status: string;
  body: string;
  target_platform: string | null;
  target_ref: string | null;
  knowledge_item_id: string | null;
  created_by_agent_run_id: string | null;
  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  published_at: string | null;
  publish_error: string | null;
  confidence: string;
  reasoning: string | null;
  evidence: string[];
  // The triggering knowledge_item's own title/body_excerpt — the original post in full, not
  // just the short evidence quotes above. Both null if there's no linked knowledge_item.
  source_title: string | null;
  source_body: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface CheckoutSessionResponse {
  checkout_url: string;
}

export interface PortalSessionResponse {
  portal_url: string;
}

export interface OAuthStartResponse {
  authorize_url: string;
}

export interface SubscriptionStatus {
  has_subscription: boolean;
  status: string | null;
  is_entitled: boolean;
  trial_ends_at: string | null;
  current_period_end: string | null;
  no_card_trial_ends_at: string | null;
}

export interface PricingTier {
  key: string;
  label: string;
  price_usd: number;
  capacity: number | null;
  spots_taken: number;
  spots_left: number | null;
  is_current: boolean;
  is_sold_out: boolean;
}

export interface PricingTiersResponse {
  tiers: PricingTier[];
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}

export interface AgentConfig {
  id: string;
  project_id: string;
  agent_key: string;
  config: Record<string, unknown>;
  schedule_cron: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentTriggerResponse {
  agent_config_id: string;
  agent_key: string;
  status: string;
}

export interface AgentRun {
  id: string;
  agent_config_id: string;
  project_id: string;
  agent_key: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  summary: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
}
