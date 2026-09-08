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
    "/support",
    "/terms",
    "/privacy",
    "/login",
    "/signup",
    "/forgot-password",
    "/blog",
    "/blog/threadly-now-in-n8n-and-openclaw",
    "/blog/approval-before-posting-is-the-ai-tool-standard",
    // 5 other blog posts (X/Twitter-specific pain points — X's ban policy, tweet decay, X
    // mentions) were unpublished, not just de-indexed, since they no longer match what the
    // product does post-Reddit-pivot: frontend/app/blog/{the-two-week-old-tweet-problem,
    // why-ai-twitter-automation-gets-accounts-banned, twitter-mentions-that-convert-dont-tag-you,
    // why-ai-twitter-replies-sound-like-a-bot, manual-scrolling-x-doesnt-scale}.
    // The 4 /alternatives/* pages (Hypefury, Tweet Hunter, Xholic AI, Bisonary — all X-only
    // tools) were deleted outright, not just de-indexed — a comparison against a competitor
    // that doesn't touch Reddit at all no longer makes sense for a Reddit-only product.
  ];
  return routes.map((route) => ({
    url: `${BASE_URL}${route}`,
    lastModified: new Date(),
  }));
}
