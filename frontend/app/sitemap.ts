import type { MetadataRoute } from "next";

// www is the canonical domain — the apex (usethreadly.co) 308-redirects here, confirmed via
// Vercel's domain config. Only public, unauthenticated marketing pages belong here; anything
// behind login (/dashboard, /approvals, /settings/*, /billing/*) would just show a crawler a
// login wall, so it's excluded rather than indexed pointlessly.
const BASE_URL = "https://www.usethreadly.co";

export default function sitemap(): MetadataRoute.Sitemap {
  const routes = [
    "",
    "/features",
    "/use-cases",
    "/faq",
    "/terms",
    "/privacy",
    "/login",
    "/signup",
    "/blog",
    "/blog/manual-scrolling-x-doesnt-scale",
  ];
  return routes.map((route) => ({
    url: `${BASE_URL}${route}`,
    lastModified: new Date(),
  }));
}
