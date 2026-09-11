"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { GoogleIcon } from "@/components/SocialIcons";
import { API_BASE_URL, ApiError, api } from "@/lib/api-client";

// Matches the exact wording AuthService.authenticate() raises for a correct password on an
// unverified account (see backend/app/services/auth_service.py) — used to decide when to
// offer the "Resend verification email" action below, not to re-derive the error copy itself.
const UNVERIFIED_EMAIL_ERROR_SUBSTRING = "verify your email";

// A real top-level browser redirect (Google needs its own page, not a fetch() call) — see
// backend/app/api/v1/auth_oauth.py.
const GOOGLE_START_URL = `${API_BASE_URL}/api/v1/auth/google/start`;

function LoginForm() {
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  // GoogleOAuthService's callback redirects back here with ?error=google_oauth_failed on
  // anything from "you denied consent" to "Google's email wasn't verified" — one generic
  // message covers all of it, same non-revealing spirit as the password login error below.
  const [error, setError] = useState<string | null>(
    searchParams.get("error") === "google_oauth_failed"
      ? "Could not sign in with Google. Try again, or use your email and password."
      : null
  );
  const [submitting, setSubmitting] = useState(false);
  const [showResend, setShowResend] = useState(false);
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setShowResend(false);
    setResent(false);
    setSubmitting(true);
    try {
      await api.login({ email, password });
      window.location.href = "/dashboard";
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many attempts. Wait a few minutes and try again.");
      } else if (err instanceof ApiError && err.status === 401) {
        // The backend's own message is already worded with security in mind — "Invalid email
        // or password" for wrong credentials (no enumeration), but a specific, more useful
        // "please verify your email" for a correct password on an unverified account (no
        // enumeration risk there, since the caller already proved they know the password).
        // Passing it through as-is, rather than overriding with a hardcoded generic string,
        // is what actually surfaces that second case to a real user.
        setError(err.message);
        setShowResend(err.message.includes(UNVERIFIED_EMAIL_ERROR_SUBSTRING));
      } else {
        setError("Something went wrong. Try again.");
      }
      setSubmitting(false);
    }
  }

  async function handleResend() {
    setResending(true);
    try {
      await api.resendVerificationEmail(email);
      // Same non-enumeration response shape as the backend — this shows regardless of
      // whether the resend actually found and emailed an account, so it never leaks that.
      setResent(true);
    } catch {
      // A 429 here is the one realistic failure — the account limiter matches the backend's
      // password-reset one (3/15min), generous enough that a real user won't hit it from
      // normal use. Fails quietly rather than adding a second error banner on top of the
      // login one already showing.
    } finally {
      setResending(false);
    }
  }

  return (
    <div className="container">
      <h1>Log in</h1>
      <div className="card">
        {error && <div className="error-banner">{error}</div>}
        <a href={GOOGLE_START_URL} className="btn btn-secondary btn-google">
          <GoogleIcon /> Continue with Google
        </a>
        <div className="auth-divider">or</div>
        {showResend &&
          (resent ? (
            <p className="muted">
              If that account needs verifying, a new link is on its way — check your inbox.
            </p>
          ) : (
            <button
              type="button"
              className="btn-secondary"
              onClick={handleResend}
              disabled={resending || !email}
            >
              {resending ? "Sending..." : "Resend verification email"}
            </button>
          ))}
        <form onSubmit={handleSubmit}>
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
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          <button type="submit" className="btn-block" disabled={submitting}>
            {submitting ? "Logging in..." : "Log in"}
          </button>
        </form>
      </div>
      <p className="muted">
        <a href="/forgot-password">Forgot password?</a>
      </p>
      <p className="muted">
        No account yet? <a href="/signup">Start your free trial</a>
      </p>
    </div>
  );
}

export default function LoginPage() {
  // useSearchParams needs a Suspense boundary in the app router — see Next.js's own
  // deprecation notice for reading it without one (same pattern as /redeem's RedeemForm).
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
