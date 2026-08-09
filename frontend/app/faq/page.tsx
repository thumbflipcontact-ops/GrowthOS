import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

export const metadata = {
  title: "FAQ — Threadly",
  description: "Common questions about how Threadly works, pricing, and the approval flow.",
};

const FAQS = [
  {
    q: "What does Threadly do?",
    a: "It watches X for conversations that match your keywords and ICP, drafts a reply with Claude, and puts it in your Approval Inbox. Nothing goes out until you personally approve it.",
  },
  {
    q: "Does Threadly post to X automatically?",
    a: "No. Every draft requires your explicit approval — this is a permanent feature of the product, not something available only in an early version. Once you approve a draft, you copy the reply and post it yourself in one click; Threadly never posts on your behalf.",
  },
  {
    q: "Which platforms does Threadly support?",
    a: "X (Twitter) today.",
  },
  {
    q: "Is there a free trial?",
    a: "Yes — 7 days, free. A valid payment card is required to start the trial, and you won't be charged if you cancel before day 7.",
  },
  {
    q: "How does pricing work?",
    a: "Pricing is tiered by signup order, applied automatically — no discount codes to enter. The first 5 customers pay $9/month, the next 10 pay $19/month, and everyone after that pays $29/month.",
  },
  {
    q: "Will my price ever go up?",
    a: "No. Once you're subscribed, your price is fixed for that subscription. Later tiers filling up as more people sign up doesn't affect customers who already joined.",
  },
  {
    q: "Can I cancel anytime?",
    a: "Yes, self-serve from your dashboard's billing page. Cancellation takes effect at the end of your current billing period — no proration for partial periods.",
  },
  {
    q: "Is my connected X account safe?",
    a: "Yes. Connecting X uses OAuth, so Threadly never sees or stores your password. Access tokens are encrypted at rest, and disconnecting immediately revokes Threadly's access.",
  },
];

export default function FaqPage() {
  return (
    <>
      <LandingNav />

      <header className="hero">
        <span className="hero-badge">
          <span className="dot" /> Frequently asked questions
        </span>
        <h1>Questions people actually ask</h1>
        <p className="lead">
          If something isn&apos;t covered here, the details also live in our{" "}
          <a href="/terms">Terms &amp; Conditions</a> and <a href="/privacy">Privacy Policy</a>.
        </p>
      </header>

      <section className="landing-section">
        <div className="faq-list">
          {FAQS.map((item) => (
            <div className="faq-item" key={item.q}>
              <h3>{item.q}</h3>
              <p>{item.a}</p>
            </div>
          ))}
        </div>
      </section>

      <LandingFooter />
    </>
  );
}
