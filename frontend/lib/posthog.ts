import posthog from "posthog-js";

// Guarded so this module is safe to import from server components too (posthog-js itself is
// client-only) — only ever actually initializes in the browser, and only once per page load.
export function initPosthog(): typeof posthog | null {
  if (typeof window === "undefined") return null;
  const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
  if (!key) return null;
  if (!posthog.__loaded) {
    posthog.init(key, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://us.i.posthog.com",
      // Next.js App Router client-side navigations don't fire a new page load, so autocapture's
      // own pageview-on-init would miss every route change after the first — PostHogProvider
      // below captures $pageview manually on each pathname change instead.
      capture_pageview: false,
      person_profiles: "identified_only",
    });
  }
  return posthog;
}

export { posthog };
