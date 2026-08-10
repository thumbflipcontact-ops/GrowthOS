import { Analytics } from "@vercel/analytics/next";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

const DESCRIPTION = "Find relevant conversations, draft replies, and approve every post yourself.";

export const metadata: Metadata = {
  metadataBase: new URL("https://www.usethreadly.co"),
  title: "Threadly",
  description: DESCRIPTION,
  openGraph: {
    title: "Threadly — Let AI find the conversation for you on X",
    description: DESCRIPTION,
    url: "https://www.usethreadly.co",
    siteName: "Threadly",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Threadly — Let AI find the conversation for you on X",
    description: DESCRIPTION,
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
        <Analytics />
      </body>
    </html>
  );
}
