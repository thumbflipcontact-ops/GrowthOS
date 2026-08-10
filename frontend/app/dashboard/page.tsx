"use client";

import { useEffect, useState } from "react";
import { TopNav } from "@/components/TopNav";
import { ApiError, api } from "@/lib/api-client";
import type { SubscriptionStatus } from "@/lib/types";
import { useSession } from "@/lib/useSession";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function BillingCard({ orgId }: { orgId: string }) {
  const [status, setStatus] = useState<SubscriptionStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [redirecting, setRedirecting] = useState(false);

  useEffect(() => {
    api
      .getSubscriptionStatus(orgId)
      .then(setStatus)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load billing status."));
  }, [orgId]);

  async function openPortal() {
    setRedirecting(true);
    try {
      const res = await api.createPortalSession(orgId);
      window.location.href = res.portal_url;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not open billing portal.");
      setRedirecting(false);
    }
  }

  if (error) return <div className="card error-banner">{error}</div>;
  if (!status) return <div className="card muted">Loading billing status...</div>;

  if (!status.has_subscription) {
    if (status.is_entitled) {
      // No-card trial still running — see docs/billing/BILLING_ARCHITECTURE.md. Subscribing
      // is optional here (locks in your tier before spots fill up), never required.
      return (
        <div className="card">
          <div className="row">
            <h2 style={{ margin: 0 }}>Billing</h2>
            <span className="badge badge-success">free trial</span>
          </div>
          {status.no_card_trial_ends_at && (
            <p className="muted">Free trial ends {formatDate(status.no_card_trial_ends_at)}. No card required.</p>
          )}
          <a href="/billing/start" className="btn-secondary">
            Subscribe now
          </a>
        </div>
      );
    }
    return (
      <div className="card">
        <div className="row">
          <h2 style={{ margin: 0 }}>Billing</h2>
          <span className="badge badge-warn">trial ended</span>
        </div>
        <p className="muted">
          Your 7-day free trial has ended. Subscribe to keep using Threadly — connecting
          accounts and drafting replies are paused until then.
        </p>
        <a href="/billing/start" className="btn">
          Subscribe now
        </a>
      </div>
    );
  }

  const badgeClass =
    status.status === "active" || status.status === "trialing"
      ? "badge-success"
      : status.status === "past_due"
        ? "badge-warn"
        : "badge-danger";

  return (
    <div className="card">
      <div className="row">
        <h2 style={{ margin: 0 }}>Billing</h2>
        <span className={`badge ${badgeClass}`}>{status.status}</span>
      </div>
      {status.status === "trialing" && status.trial_ends_at && (
        <p className="muted">Trial ends {formatDate(status.trial_ends_at)}.</p>
      )}
      {status.status === "active" && status.current_period_end && (
        <p className="muted">Renews {formatDate(status.current_period_end)}.</p>
      )}
      {status.status === "past_due" && (
        <p className="muted">Your last payment failed — update your card to keep your subscription active.</p>
      )}
      {status.status === "canceled" && (
        <p className="muted">Your subscription is canceled. Publishing and new connections are paused.</p>
      )}
      <button type="button" className="btn-secondary" onClick={openPortal} disabled={redirecting}>
        {redirecting ? "Opening..." : "Manage billing"}
      </button>
    </div>
  );
}

export default function DashboardPage() {
  const { loading, user, organization, project, error } = useSession();

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
        <h1>Welcome, {user?.name}</h1>
        <p className="subtitle">{organization.name}</p>

        <BillingCard orgId={organization.id} />

        <div className="card">
          <h2>Get started</h2>
          <div className="stack">
            <a href="/settings/plugins" className="btn btn-secondary">
              Connect an account (X)
            </a>
            <a href="/approvals" className="btn btn-secondary">
              Review drafted posts
            </a>
          </div>
        </div>
      </div>
    </>
  );
}
