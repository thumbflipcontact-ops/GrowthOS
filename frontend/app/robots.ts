import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/dashboard", "/approvals", "/settings/", "/billing/"],
    },
    sitemap: "https://www.usethreadly.co/sitemap.xml",
  };
}
