"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ApiError, api } from "@/lib/api-client";

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }

    setSubmitting(true);
    try {
      await api.resetPassword(token, password);
      window.location.href = "/dashboard";
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("This reset link is invalid or has expired — request a new one.");
      } else {
        setError("Something went wrong. Try again.");
      }
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <p>
        This reset link is missing its token — check the link from your email, or{" "}
        <a href="/forgot-password">request a new one</a>.
      </p>
    );
  }

  return (
    <>
      {error && <div className="error-banner">{error}</div>}
      <form onSubmit={handleSubmit}>
        <label htmlFor="password">New password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={12}
          required
        />
        <p className="muted">At least 12 characters.</p>

        <label htmlFor="confirmPassword">Confirm new password</label>
        <input
          id="confirmPassword"
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          minLength={12}
          required
        />

        <button type="submit" className="btn-block" disabled={submitting}>
          {submitting ? "Resetting..." : "Reset password"}
        </button>
      </form>
    </>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="container">
      <h1>Choose a new password</h1>
      <div className="card">
        <Suspense fallback={null}>
          <ResetPasswordForm />
        </Suspense>
      </div>
    </div>
  );
}
