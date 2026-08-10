import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

export const metadata = {
  title: "Blog — Threadly",
  description:
    "Notes on finding real conversations on X, replying well, and growing without a growth team.",
};

// Hand-written posts, same pattern as the FAQ/use-cases arrays — no CMS, just a page per post
// under app/blog/[slug]/. Add new entries here as posts are written; each `href` must have a
// matching page.tsx and be added to app/sitemap.ts.
const POSTS = [
  {
    href: "/blog/manual-scrolling-x-doesnt-scale",
    title: "Why Manually Scrolling X For Leads Doesn't Scale (And What Actually Fixes It)",
    excerpt:
      "The signal-to-noise ratio of manual monitoring is brutal, and the moment you stop scrolling is the moment you miss the conversation. Here's what actually works instead.",
    date: "August 10, 2026",
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
          Short, specific writing on the actual problem of growing on X as a founder — no
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
