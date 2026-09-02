import { Analytics } from "@vercel/analytics/next";
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { PostHogProvider } from "@/components/PostHogProvider";
import "./globals.css";

const DESCRIPTION = "Find relevant conversations, draft replies, and approve every post yourself.";

// Without this, mobile browsers render the page at a "desktop-width" layout viewport
// (~980-1024px) and scale it to fit the screen — CSS media queries then evaluate against
// that inflated width instead of the real device width, and `position: fixed` elements can
// visibly drift/scroll instead of staying pinned, a well-known class of iOS Safari bug tied
// to exactly this missing-viewport-tag situation.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export const metadata: Metadata = {
  metadataBase: new URL("https://www.usethreadly.co"),
  title: "Threadly — AI Twitter Comment Bot for Finding Leads",
  description: DESCRIPTION,
  openGraph: {
    title: "Threadly — AI finds your next customer on X",
    description: DESCRIPTION,
    url: "https://www.usethreadly.co",
    siteName: "Threadly",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Threadly — AI finds your next customer on X",
    description: DESCRIPTION,
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <PostHogProvider>
          {children}
          <Analytics />
        </PostHogProvider>
      </body>
    </html>
  );
}
