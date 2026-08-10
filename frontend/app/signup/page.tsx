"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { initPosthog } from "@/lib/posthog";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 90);
}

export default function SignupPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    setSubmitting(true);
    try {
      // No business-name field in this form — every account still needs an Organization
      // under the hood (see ARCHITECTURE.md's multi-tenancy model), so one is created
      // automatically from the person's own name rather than asking them to name it.
      const slug = slugify(name) || "workspace";
      await api.register({
        org_name: `${name}'s Workspace`,
        org_slug: `${slug}-${Date.now().toString(36)}`,
        email,
        name,
        password,
      });
      // Captured under the anonymous distinct_id — useSession's identify(organization.id)
      // call on the very next page load (dashboard) merges this event into that org's
      // timeline, PostHog's standard anonymous-then-identified pattern.
      initPosthog()?.capture("signup_completed");
      // Registration signs the browser in directly (session cookie set on the response), and
      // the org is immediately entitled via the no-card trial (see
      // docs/billing/BILLING_ARCHITECTURE.md) — no billing step required before the
      // dashboard, unlike the old card-required flow.
      window.location.href = "/dashboard";
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
      setSubmitting(false);
    }
  }

  return (
    <div className="container">
      <h1>Start your free trial</h1>
      <p className="subtitle">7 days free. No card required.</p>
      <div className="card">
        {error && <div className="error-banner">{error}</div>}
        <form onSubmit={handleSubmit}>
          <label htmlFor="name">Your name</label>
          <input id="name" value={name} onChange={(e) => setName(e.target.value)} required />

          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            minLength={12}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <p className="muted">At least 12 characters.</p>

          <button type="submit" className="btn-block" disabled={submitting}>
            {submitting ? "Creating account..." : "Create account & start free trial"}
          </button>
        </form>
      </div>
      <p className="muted">
        By creating an account you agree to Threadly&apos;s{" "}
        <a href="/terms">Terms &amp; Conditions</a> and <a href="/privacy">Privacy Policy</a>.
      </p>
      <p className="muted">
        Already have an account? <a href="/login">Log in</a>
      </p>
    </div>
  );
}
