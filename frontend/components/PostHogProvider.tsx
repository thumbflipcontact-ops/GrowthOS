"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { PostHogProvider as PHProvider } from "posthog-js/react";
import { initPosthog, posthog } from "@/lib/posthog";

// App Router client-side navigations don't fire a new page load, so this fires the $pageview
// PostHog's own autocapture would otherwise only send once, on the very first load.
function PostHogPageview() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (!pathname) return;
    const client = initPosthog();
    if (!client) return;
    let url = window.origin + pathname;
    const query = searchParams?.toString();
    if (query) url += `?${query}`;
    client.capture("$pageview", { $current_url: url });
  }, [pathname, searchParams]);

  return null;
}

export function PostHogProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    initPosthog();
  }, []);

  return (
    <PHProvider client={posthog}>
      <Suspense fallback={null}>
        <PostHogPageview />
      </Suspense>
      {children}
    </PHProvider>
  );
}
