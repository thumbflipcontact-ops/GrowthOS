import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

export const metadata = {
  title: "Features — Threadly",
  description:
    "What Threadly actually does: finds relevant conversations on X, drafts a reply with AI, and never posts anything without your approval.",
};

const FEATURES = [
  {
    title: "Conversation Finder",
    body: "Give it your keywords and ICP once. It scans X on a schedule and surfaces the posts that actually match what you're building — no more refreshing search tabs all day.",
  },
  {
    title: "AI-drafted replies",
    body: "Claude drafts a reply grounded in the original post, citing what the person actually said. You always see the full source post next to the draft, not just a snippet.",
  },
  {
    title: "Approval Inbox",
    body: "Every draft sits in your Approval Inbox until you personally read and approve it. This is permanent — Threadly never publishes anything on its own, on any tier.",
  },
  {
    title: "One-click posting",
    body: "Approve a draft and it's ready to go: copy the reply text, jump straight to the original post on X, paste, and mark it posted. Takes seconds, but the actual posting is always yours.",
  },
  {
    title: "A record of everywhere you've replied",
    body: "Every reply you mark as posted is logged with a timestamp and a link back to the original post — so you always know where you've already commented, instead of losing track and re-searching the same conversations.",
  },
  {
    title: "Tiered founding pricing",
    body: "The earlier you sign up, the less you pay — and it's locked in for as long as you stay subscribed. No coupon codes, nothing to enter.",
  },
  {
    title: "Cancel anytime",
    body: "Self-serve from your dashboard's billing page. No calls, no emails, no retention flow.",
  },
];

export default function FeaturesPage() {
  return (
    <>
      <LandingNav />

      <header className="hero">
        <span className="hero-badge">
          <span className="dot" /> Everything Threadly does
        </span>
        <h1>Built to find the conversation, not just post to one.</h1>
        <p className="lead">
          Threadly watches X for conversations worth joining, drafts a reply with Claude, and
          waits for you to say yes. Here&apos;s exactly what that looks like.
        </p>
        <div className="hero-ctas">
          <a href="/signup" className="btn btn-grad">
            Start your 7-day free trial
          </a>
          <a href="/#pricing" className="btn-ghost">
            See pricing
          </a>
        </div>
      </header>

      <section className="landing-section">
        <div className="feature-grid">
          {FEATURES.map((feature) => (
            <div className="step-card" key={feature.title}>
              <h3>{feature.title}</h3>
              <p>{feature.body}</p>
            </div>
          ))}
        </div>
      </section>

      <LandingFooter />
    </>
  );
}
