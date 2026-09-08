"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
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

// Separate from /signup on purpose — a lifetime-deal buyer isn't going through Polar
// Checkout at all, and mixing an optional code field into the regular signup form would
// complicate the common case for the sake of the rare one. AppSumo can point buyers here
// with ?code=... pre-filled, or a buyer can paste it in by hand.
function RedeemForm() {
  const searchParams = useSearchParams();
  const [code, setCode] = useState(searchParams.get("code") ?? "");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [registered, setRegistered] = useState(false);
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const slug = slugify(name) || "workspace";
      await api.redeemLtdCode({
        code: code.trim(),
        org_name: `${name}'s Workspace`,
        org_slug: `${slug}-${Date.now().toString(36)}`,
        email,
        name,
        password,
      });
      initPosthog()?.capture("ltd_code_redeemed");
      setRegistered(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    setResending(true);
    try {
      await api.resendVerificationEmail(email);
      setResent(true);
    } catch {
      // Same reasoning as /signup's own handleResend.
    } finally {
      setResending(false);
    }
  }

  if (registered) {
    return (
      <div className="container">
        <h1>Check your email</h1>
        <div className="card">
          <p>
            We&apos;ve sent a verification link to <strong>{email}</strong>. Click it to
            activate your account.
          </p>
        </div>
        <p className="muted">
          {resent ? (
            "Sent again — check your inbox (and spam folder)."
          ) : (
            <>
              Didn&apos;t get it?{" "}
              <button
                type="button"
                onClick={handleResend}
                disabled={resending}
                className="link-button"
              >
                {resending ? "Sending..." : "Resend verification email"}
              </button>
            </>
          )}
        </p>
        <p className="muted">
          Already have an account? <a href="/login">Log in</a>
        </p>
      </div>
    );
  }

  return (
    <div className="container">
      <h1>Redeem your lifetime deal</h1>
      <p className="subtitle">One-time code, one account, activated immediately.</p>
      <div className="card">
        {error && <div className="error-banner">{error}</div>}
        <form onSubmit={handleSubmit}>
          <label htmlFor="code">Redemption code</label>
          <input
            id="code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="e.g. K7XPQ29MRT"
            required
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
            {submitting ? "Redeeming..." : "Redeem code & create account"}
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

export default function RedeemPage() {
  // useSearchParams needs a Suspense boundary in the app router — see Next.js's own
  // deprecation notice for reading it without one.
  return (
    <Suspense fallback={null}>
      <RedeemForm />
    </Suspense>
  );
}
