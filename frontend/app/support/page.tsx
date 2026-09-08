import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

export const metadata = {
  title: "Support — Threadly",
  description: "Get help with Threadly — email amol.parikh@gmail.com, we reply within 24 hours.",
  alternates: { canonical: "/support" },
};

const SUPPORT_EMAIL = "amol.parikh@gmail.com";

const COMMON_ISSUES = [
  {
    q: "I never got my verification email",
    a: "Check spam first. If it's not there, go to the login page and use \"Resend verification email\" — it sends a fresh one immediately, no need to sign up again.",
  },
  {
    q: "My leads don't look relevant",
    a: "This almost always comes down to keywords. Specific phrases someone would actually type (\"struggling to rank\", \"nobody's finding my blog\") work far better than a single broad word (\"SEO\"). Edit your keywords any time from Settings → Agents.",
  },
  {
    q: "I want to cancel my subscription",
    a: "Self-serve from your dashboard's Billing page — cancellation takes effect at the end of your current billing period, no proration for partial periods.",
  },
  {
    q: "I found a bug or something looks broken",
    a: `Email us at ${SUPPORT_EMAIL} with what you were doing and what you saw — screenshots help a lot. We reply within 24 hours.`,
  },
  {
    q: "I have a feature request or general question",
    a: `We read every email — send it to ${SUPPORT_EMAIL} and we'll get back to you within 24 hours.`,
  },
];

const SUPPORT_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: COMMON_ISSUES.map((item) => ({
    "@type": "Question",
    name: item.q,
    acceptedAnswer: { "@type": "Answer", text: item.a },
  })),
};

export default function SupportPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(SUPPORT_JSON_LD) }}
      />
      <LandingNav />

      <header className="hero">
        <span className="hero-badge">
          <span className="dot" /> Support
        </span>
        <h1>We&apos;re here to help</h1>
        <p className="lead">
          Email <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a> any time — we reply
          within 24 hours.
        </p>
      </header>

      <section className="landing-section">
        <div className="card" style={{ maxWidth: 560, margin: "0 auto 64px", textAlign: "center" }}>
          <h3 style={{ marginTop: 0 }}>Contact us</h3>
          <p className="muted" style={{ marginBottom: 16 }}>
            Bug reports, billing questions, feature requests — whatever it is, it goes straight
            to a real person, not a ticket queue.
          </p>
          <a href={`mailto:${SUPPORT_EMAIL}`} className="btn btn-grad">
            Email {SUPPORT_EMAIL}
          </a>
          <p className="muted" style={{ marginTop: 16, marginBottom: 0, fontSize: 13 }}>
            24-hour reply commitment, every day of the week.
          </p>
        </div>

        <h2 style={{ textAlign: "center", marginBottom: 8 }}>Common issues</h2>
        <div className="faq-list">
          {COMMON_ISSUES.map((item) => (
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
