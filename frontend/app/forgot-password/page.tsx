"use client";

import { useState } from "react";
import { api } from "@/lib/api-client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api.requestPasswordReset(email);
    } catch {
      // Deliberately ignored — the backend already returns the same response whether or not
      // the email has an account, so there's nothing distinct to show on failure either.
    }
    // Always show the same success state, matching the backend's own non-enumeration rule:
    // never reveal whether this email exists.
    setSubmitted(true);
    setSubmitting(false);
  }

  return (
    <div className="container">
      <h1>Reset your password</h1>
      <div className="card">
        {submitted ? (
          <p>
            If that email has a Threadly account, we&apos;ve sent a link to reset your
            password. It expires in 1 hour.
          </p>
        ) : (
          <form onSubmit={handleSubmit}>
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />

            <button type="submit" className="btn-block" disabled={submitting}>
              {submitting ? "Sending..." : "Send reset link"}
            </button>
          </form>
        )}
      </div>
      <p className="muted">
        Remembered it? <a href="/login">Log in</a>
      </p>
    </div>
  );
}
