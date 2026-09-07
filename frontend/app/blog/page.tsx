import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

export const metadata = {
  title: "Blog — Threadly",
  description:
    "Notes on finding real conversations on Reddit, replying well, and growing without a growth team.",
};

// Hand-written posts, same pattern as the FAQ/use-cases arrays — no CMS, just a page per post
// under app/blog/[slug]/. Add new entries here as posts are written; each `href` must have a
// matching page.tsx and be added to app/sitemap.ts.
const POSTS = [
  {
    href: "/blog/threadly-now-in-n8n-and-openclaw",
    title: "Threadly Now Works Inside n8n and OpenClaw — Not Just Its Own Dashboard",
    excerpt:
      "Threadly's Approval Inbox now shows up wherever you already work: as an n8n community node, and as a ClawHub skill for OpenClaw agents.",
    date: "August 18, 2026",
  },
  {
    href: "/blog/approval-before-posting-is-the-ai-tool-standard",
    title: "Why “Approve Before It Posts” Is Becoming the AI Tool Standard",
    excerpt:
      "Reddit reply tools and review-management platforms are marketing human approval as a feature, not an afterthought. Here's why that trend is happening across categories.",
    date: "August 17, 2026",
  },
];

export default function BlogIndexPage() {
  return (
    <>
      <LandingNav />

      <header className="hero">
        <span className="hero-badge">
          <span className="dot" /> Blog
        </span>
        <h1>Notes on finding conversations, not just scheduling posts.</h1>
        <p className="lead">
          Short, specific writing on the actual problem of growing on Reddit as a founder — no
          generic &quot;10 tips&quot; filler.
        </p>
      </header>

      <section className="landing-section">
        <div className="feature-grid">
          {POSTS.map((post) => (
            <a
              className="step-card"
              href={post.href}
              key={post.href}
              style={{ display: "block", textDecoration: "none", color: "inherit" }}
            >
              <h3>{post.title}</h3>
              <p>{post.excerpt}</p>
              <p className="muted" style={{ marginTop: 12, fontSize: 13 }}>
                {post.date}
              </p>
            </a>
          ))}
        </div>
      </section>

      <LandingFooter />
    </>
  );
}
