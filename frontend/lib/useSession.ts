"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "./api-client";
import type { Organization, Project, User } from "./types";

interface SessionState {
  loading: boolean;
  user: User | null;
  organization: Organization | null;
  project: Project | null;
  error: string | null;
}

// Every authenticated page needs (user, org, project) to make any API call — this is the one
// place that resolves all three, including auto-creating a single default project on first
// login so a brand-new customer never has to understand the org/project distinction. A
// second project (a second SaaS business) is something they can create later; this app has
// no UI for that yet — see frontend/README.md's "Intended structure."
export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>({
    loading: true,
    user: null,
    organization: null,
    project: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const user = await api.me();
        const organizations = await api.myOrganizations();
        const organization = organizations[0] ?? null;

        let project: Project | null = null;
        if (organization) {
          const projects = await api.listProjects(organization.id);
          project = projects[0] ?? null;
          if (!project) {
            try {
              project = await api.createProject(organization.id, {
                name: "My Business",
                slug: "default",
              });
            } catch (createErr) {
              // Lost a race creating the default project — another concurrent call for the
              // same org got there first (React's dev-mode double-effect-invoke reliably
              // triggers this, but it's a real race regardless of cause: a second tab, a
              // retried request). The project now exists; fetch it instead of surfacing this
              // as a real error.
              if (createErr instanceof ApiError && createErr.code === "validation_error") {
                const retryProjects = await api.listProjects(organization.id);
                project = retryProjects[0] ?? null;
              } else {
                throw createErr;
              }
            }
          }
        }

        if (!cancelled) {
          setState({ loading: false, user, organization, project, error: null });
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          window.location.href = "/login";
          return;
        }
        const message = err instanceof ApiError ? err.message : "Something went wrong.";
        setState({ loading: false, user: null, organization: null, project: null, error: message });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
