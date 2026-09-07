"use client";

import { Logo } from "@/components/Logo";
import { api } from "@/lib/api-client";

export function TopNav() {
  async function handleLogout() {
    await api.logout().catch(() => undefined);
    window.location.href = "/login";
  }

  return (
    <nav className="top-nav">
      <div className="top-nav-inner">
        <div>
          <a href="/dashboard" className="brand">
            <Logo size={24} />
            Threadly
          </a>
          <a href="/settings/agents">Leads Finder</a>
          <a href="/approvals">Approvals</a>
          <a href="/ready-to-post">Ready to Post</a>
          <a href="/posted">Posted</a>
        </div>
        <button className="btn-secondary" onClick={handleLogout} type="button">
          Log out
        </button>
      </div>
    </nav>
  );
}
