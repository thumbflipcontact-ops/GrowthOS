"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 90);
}

export default function SignupPage() {
  const [businessName, setBusinessName] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const slug = slugify(businessName);
    if (slug.length < 1) {
      setError("Business name must contain at least one letter or number.");
      return;
    }

    setSubmitting(true);
    try {
      await api.register({
        org_name: businessName,
        org_slug: `${slug}-${Date.now().toString(36)}`,
        email,
        name,
        password,
      });
      // Registration signs the browser in directly (session cookie set on the response) —
      // straight to billing next, since a trial-less, unentitled account can't do anything
      // yet. See docs/billing/BILLING_ARCHITECTURE.md.
      window.location.href = "/billing/start";
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
      setSubmitting(false);
    }
  }

  return (
    <div className="container">
      <h1>Start your free trial</h1>
      <p className="subtitle">7 days free. A card is required to start the trial.</p>
      <div className="card">
        {error && <div className="error-banner">{error}</div>}
        <form onSubmit={handleSubmit}>
          <label htmlFor="businessName">Business name</label>
          <input
            id="businessName"
            value={businessName}
            onChange={(e) => setBusinessName(e.target.value)}
            required
            placeholder="Acme SEO"
          />

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
            {submitting ? "Creating account..." : "Create account & continue to billing"}
          </button>
        </form>
      </div>
      <p className="muted">
        Already have an account? <a href="/login">Log in</a>
      </p>
    </div>
  );
}
