"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { initPosthog } from "@/lib/posthog";
import { useSession } from "@/lib/useSession";

export default function BillingStartPage() {
  const { loading, organization, error: sessionError } = useSession();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (loading || !organization) return;
    let cancelled = false;

    api
      .createCheckoutSession(organization.id)
      .then((res) => {
        if (!cancelled) {
          initPosthog()?.capture("checkout_started");
          window.location.href = res.checkout_url;
        }
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.code === "billing_not_configured") {
          setError(
            "Billing isn't set up on this deployment yet — POLAR_ACCESS_TOKEN/POLAR_PRODUCT_ID " +
              "are missing. See docs/billing/BILLING_ARCHITECTURE.md's Setup section."
          );
        } else {
          setError(err instanceof ApiError ? err.message : "Something went wrong.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [loading, organization]);

  return (
    <div className="container">
      <h1>Setting up billing...</h1>
      {(error || sessionError) && (
        <div className="error-banner">{error ?? sessionError}</div>
      )}
      {!error && !sessionError && (
        <p className="muted">Redirecting you to a secure checkout page.</p>
      )}
      {error && (
        <a href="/dashboard" className="btn btn-secondary">
          Go to dashboard instead
        </a>
      )}
    </div>
  );
}
