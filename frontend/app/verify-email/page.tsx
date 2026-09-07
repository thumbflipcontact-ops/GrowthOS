"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api-client";

type Status = "verifying" | "success" | "error";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [status, setStatus] = useState<Status>(token ? "verifying" : "error");

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api
      .verifyEmail(token)
      .then(() => {
        if (cancelled) return;
        setStatus("success");
        // Verifying already granted a session (same as reset-password) — straight to the
        // dashboard, no separate login step.
        window.location.href = "/dashboard";
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (status === "verifying") {
    return <p className="muted">Verifying your email...</p>;
  }

  if (status === "error") {
    return (
      <p>
        {token
          ? "This verification link is invalid or has expired."
          : "This verification link is missing its token — check the link from your email."}{" "}
        <a href="/signup">Sign up again</a> to get a new one.
      </p>
    );
  }

  return <p className="muted">Verified — taking you to your dashboard...</p>;
}

export default function VerifyEmailPage() {
  return (
    <div className="container">
      <h1>Verify your email</h1>
      <div className="card">
        <Suspense fallback={null}>
          <VerifyEmailContent />
        </Suspense>
      </div>
    </div>
  );
}
