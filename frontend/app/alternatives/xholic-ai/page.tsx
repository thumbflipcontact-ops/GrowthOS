import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

const TITLE = "Xholic AI Alternative: Threadly vs Xholic AI Compared";
const DESCRIPTION =
  "A factual, feature-by-feature comparison of Threadly and Xholic AI for finding conversations and replying on X — pricing, workflow, and what each tool actually does.";

export const metadata = {
  title: `${TITLE} — Threadly`,
  description: DESCRIPTION,
  openGraph: { title: TITLE, description: DESCRIPTION, type: "article" },
};

// Every figure below was checked directly against xholic.ai/pricing and Threadly's own live
// pricing on the same day this page was last updated — see the "Last verified" date. Update
// both sides together if either product's pricing or feature set changes.
const LAST_VERIFIED = "September 4, 2026";

const COMPARISON_ROWS: [string, string, string][] = [
  ["What it's for", "AI growth workspace for X: reply suggestions, content ideas, remixing, scheduling, and a \"Brain\" agent for daily growth ideas", "Finds relevant X conversations and drafts replies for you to review and approve"],
  ["Starting price", "$39/mo (Pro)", "From $9/mo — tiered by signup order, locked in for as long as you stay subscribed"],
  ["Free trial", "7 days, $0 to start", "7 days, no card required"],
  ["Interface", "Chrome extension — works inside your X feed while you're actively browsing", "Separate dashboard — runs on a schedule in the background, no need to be on X"],
  ["Dedicated conversation discovery", "\"Conversation Network\" — listed as \"Coming soon\" on their own pricing page, not live yet", "Core, live feature: scans X on a schedule for posts matching your keywords"],
  ["AI-drafted replies", "Yes — tailored suggestions via Reply Deck, refined as you use it", "Yes, on every plan"],
  ["Who decides what gets posted", "You — Xholic markets itself explicitly as suggestions only, not automated posting", "You — every draft requires approval in your Approval Inbox before you copy/paste it"],
  ["Post/thread scheduling", "Yes — 50 to 2,500 scheduled posts/month depending on tier", "Not offered — Threadly doesn't schedule original posts, only drafts replies"],
  ["Connected X accounts", "1 (Pro) up to 12 (Ultra)", "Not limited by connected accounts the same way"],
  ["Human ghostwriting service", "Yes, on Ultra ($199/mo): 3 tweets/day written by a professional ghostwriter", "Not offered"],
];

const JSON_LD = {
  "@context": "https://schema.org",
  "@type": "Article",
  headline: TITLE,
  description: DESCRIPTION,
  datePublished: "2026-09-04",
  dateModified: "2026-09-04",
  author: { "@type": "Organization", name: "Threadly" },
};

const FAQ_ITEMS: [string, string][] = [
  [
    "What's the main difference between Xholic AI and Threadly?",
    "Xholic AI is a broader X growth workspace you use while actively browsing your feed via a Chrome extension — reply suggestions, content remixing, scheduling, and a \"Brain\" agent for growth ideas. Threadly runs in the background on a schedule and doesn't require you to be on X at all: it finds conversations matching your keywords and drafts a reply for you to approve in a separate inbox. Xholic's own equivalent to conversation discovery, \"Conversation Network,\" is listed as \"Coming soon\" on their pricing page as of this writing — Threadly's version is live today.",
  ],
  [
    "Does Xholic AI auto-post without my approval?",
    "No. Xholic markets itself explicitly around keeping you in control — one of their own published testimonials states: \"I like that Xholic doesn't try to run my account for me... I still decide what gets edited, posted, or ignored.\" This is different from tools with unattended Auto-DM or Auto-comment features; Xholic and Threadly are actually similar on this specific point, just implemented differently (in-feed suggestions vs. a formal approval queue).",
  ],
  [
    "Does Threadly do everything Xholic AI does?",
    "No. Threadly doesn't schedule posts, doesn't have a content-remixing or growth-idea \"Brain\" agent, and doesn't offer ghostwriting. If you want a broad, all-in-one X growth workspace, Xholic covers more ground. If what you specifically need is background conversation discovery and AI-drafted replies without paying for a wider content suite, that's what Threadly is built for.",
  ],
  [
    "Can I use both?",
    "Yes. Some users keep Xholic for its browsing-companion workflow — content ideas, remixing, scheduling — and use Threadly separately for background conversation discovery, since Xholic's own dedicated discovery feature isn't live yet.",
  ],
];

const FAQ_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: FAQ_ITEMS.map(([question, answer]) => ({
    "@type": "Question",
    name: question,
    acceptedAnswer: { "@type": "Answer", text: answer },
  })),
};

export default function XholicAlternativePage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(FAQ_JSON_LD) }}
      />
      <LandingNav />

      <article className="legal">
        <h1>{TITLE}</h1>
        <p className="updated">Last verified {LAST_VERIFIED} · Threadly</p>

        <p>
          <strong>
            Short answer: Xholic AI is a broader X growth workspace — reply suggestions,
            content remixing, scheduling, and a growth-idea agent — used via a Chrome extension
            while you browse. Threadly does one narrower thing, running in the background: it
            finds real X conversations matching your keywords and drafts a reply with AI for
            you to approve.
          </strong>{" "}
          Both keep a human in control of what actually gets posted — they just get there
          differently. Here&apos;s exactly how they compare, feature by feature.
        </p>

        <h2>Feature-by-feature comparison</h2>
        <div className="compare-table-wrap">
          <table className="compare-table">
            <thead>
              <tr>
                <th></th>
                <th>Xholic AI</th>
                <th>Threadly</th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON_ROWS.map(([label, xholic, threadly]) => (
                <tr key={label}>
                  <th scope="row">{label}</th>
                  <td>{xholic}</td>
                  <td>{threadly}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="table-note">
          Figures checked directly against{" "}
          <a href="https://xholic.ai/pricing" target="_blank" rel="noopener noreferrer">
            xholic.ai/pricing
          </a>{" "}
          and Threadly&apos;s own pricing as of {LAST_VERIFIED}.
        </p>

        <h2>Where Xholic AI wins</h2>
        <p>
          If you want one Chrome-extension workspace for writing replies, remixing viral posts,
          getting daily content ideas from an AI agent, scheduling your own posts, and even
          human ghostwriting on the top tier, Xholic covers a lot more of the X workflow than
          Threadly does. Threadly isn&apos;t a content-creation or scheduling tool.
        </p>

        <h2>Where Threadly wins</h2>
        <p>
          Xholic is built to use while you&apos;re actively scrolling your X feed. Threadly runs
          on a schedule in the background and surfaces what it finds in an Approval Inbox you
          check on your own time — you don&apos;t need to be browsing X at all for it to work.
          Xholic&apos;s own dedicated conversation-discovery feature, Conversation Network, is
          still listed as &quot;Coming soon&quot;; Threadly&apos;s equivalent has been a live,
          core feature since launch. Threadly also starts significantly cheaper, at $9/mo
          versus Xholic&apos;s $39/mo entry price.
        </p>

        <h2>Frequently asked questions</h2>
        {FAQ_ITEMS.map(([question, answer]) => (
          <div key={question}>
            <h3>{question}</h3>
            <p>{answer}</p>
          </div>
        ))}

        <h2>Try Threadly</h2>
        <p>
          If what you need is background conversation discovery on X and AI-drafted replies
          you still fully control, Threadly is built specifically for that.
        </p>
        <p>
          <a href="/signup">Start a 7-day free trial</a> — no card required.
        </p>
      </article>

      <LandingFooter />
    </>
  );
}
