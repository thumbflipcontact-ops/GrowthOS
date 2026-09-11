"use client";

import { useState } from "react";
import { GoogleIcon } from "@/components/SocialIcons";
import { API_BASE_URL, ApiError, api } from "@/lib/api-client";
import { initPosthog } from "@/lib/posthog";

// A real top-level browser redirect (Google needs its own page, not a fetch() call) — see
// backend/app/api/v1/auth_oauth.py. A brand-new Google signup skips this page's own
// "Check your email" step entirely — Google already verified the address, so
// GoogleOAuthService sets email_verified_at immediately and the callback lands the browser
// straight on /dashboard, signed in.
const GOOGLE_START_URL = `${API_BASE_URL}/api/v1/auth/google/start`;

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
  // Honeypot — matches backend/app/schemas/auth.py's RegisterRequest.website. Rendered visually
  // hidden and out of tab order below; a real person never sees or fills this, so a non-empty
  // value here means whatever submitted this form filled in every input it could find.
  const [website, setWebsite] = useState("");
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
        website,
      });
      // Captured under the anonymous distinct_id — useSession's identify(organization.id)
      // call on the first post-verification page load merges this event into that org's
      // timeline, PostHog's standard anonymous-then-identified pattern.
      initPosthog()?.capture("signup_completed");
      // Registration no longer signs the browser in directly — it withholds a session until
      // the emailed verification link is clicked (see
      // backend/app/services/email_verification_service.py), so there's no dashboard
      // redirect here anymore.
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
      // Same reasoning as the login page's own handleResend — a 429 is the one realistic
      // failure, generous enough that a real user won't hit it from normal use, and not worth
      // a second error banner here.
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
            activate your account and start your free trial.
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
      <h1>Start your free trial</h1>
      <p className="subtitle">7 days free. No card required.</p>
      <div className="card">
        {error && <div className="error-banner">{error}</div>}
        <a href={GOOGLE_START_URL} className="btn btn-secondary btn-google">
          <GoogleIcon /> Continue with Google
        </a>
        <div className="auth-divider">or</div>
        <form onSubmit={handleSubmit}>
          {/* Honeypot — invisible and unreachable by tab order for a real person; see the
              `website` state's comment above. Not `display:none`/`hidden`, which some bots
              skip — off-screen positioning still gets auto-filled by a naive form-filler. */}
          <div style={{ position: "absolute", left: "-9999px", top: "-9999px" }} aria-hidden="true">
            <label htmlFor="website">Website</label>
            <input
              id="website"
              name="website"
              type="text"
              tabIndex={-1}
              autoComplete="off"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
            />
          </div>

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
