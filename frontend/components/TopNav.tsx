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
          <a href="/settings/plugins">Connections</a>
          <a href="/settings/agents">Agent settings</a>
          <a href="/approvals">Approvals</a>
        </div>
        <button className="btn-secondary" onClick={handleLogout} type="button">
          Log out
        </button>
      </div>
    </nav>
  );
}
