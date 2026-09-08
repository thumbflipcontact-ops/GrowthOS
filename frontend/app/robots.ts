import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // /redeem is only ever useful reached via a specific AppSumo code link, not something
      // worth ranking in search for its own sake — same reasoning as /billing/, /dashboard.
      disallow: ["/dashboard", "/approvals", "/settings/", "/billing/", "/redeem"],
    },
    sitemap: "https://www.usethreadly.co/sitemap.xml",
  };
}
