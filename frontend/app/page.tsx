"use client";

import { useEffect } from "react";
import { ApiError, api } from "@/lib/api-client";

export default function RootPage() {
  useEffect(() => {
    api
      .me()
      .then(() => {
        window.location.href = "/dashboard";
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          window.location.href = "/login";
        }
      });
  }, []);

  return (
    <div className="container">
      <p className="muted">Loading...</p>
    </div>
  );
}
