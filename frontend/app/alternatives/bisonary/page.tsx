import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

const TITLE = "Bisonary Alternative: Threadly vs Bisonary Compared";
const DESCRIPTION =
  "A factual, feature-by-feature comparison of Threadly and Bisonary for finding conversations and replying on X — pricing, workflow, and what each tool actually does.";

export const metadata = {
  title: `${TITLE} — Threadly`,
  description: DESCRIPTION,
  openGraph: { title: TITLE, description: DESCRIPTION, type: "article" },
};

// Every figure below was checked directly against bisonary.com/pricing and Threadly's own
// live pricing on the same day this page was last updated — see the "Last verified" date.
// Update both sides together if either product's pricing or feature set changes.
const LAST_VERIFIED = "September 5, 2026";

const COMPARISON_ROWS: [string, string, string][] = [
  ["What it's for", "Writing copilot for X: helps you draft a better reply, in your own voice, to a post you've already found", "Finds relevant X conversations and drafts replies for you to review and approve"],
  ["Starting price", "Credit-based: $9/mo (1,500 credits) or $5 one-time (500 credits)", "From $9/mo — tiered by signup order, locked in for as long as you stay subscribed"],
  ["Pricing model", "Pay-per-action credits — a reply suggestion costs 3 credits each", "Flat monthly subscription, unlimited approved connections"],
  ["Free trial", "200 free credits, no card required, no time limit", "7 days, no card required"],
  ["Conversation discovery", "Not offered — you find the post yourself while browsing, then Bisonary helps you write the reply", "Core feature: scans X on a schedule for posts matching your keywords"],
  ["Interface", "Chrome extension — works inside your X feed while you're actively browsing", "Separate dashboard — runs on a schedule in the background, no need to be on X"],
  ["AI-drafted replies", "Yes — 3 contextual reply drafts per post, shaped to your voice", "Yes, grounded in the original post, on every plan"],
  ["Voice/style matching", "Yes — learns your writing style from imported tweets; depth increases with paid usage", "Not a feature — drafts are grounded in the conversation, not a personal voice model"],
  ["Who decides what gets posted", "You — Bisonary markets itself explicitly as \"not a reply bot\"", "You — every draft requires approval in your Approval Inbox before you copy/paste it"],
];

const JSON_LD = {
  "@context": "https://schema.org",
  "@type": "Article",
  headline: TITLE,
  description: DESCRIPTION,
  datePublished: "2026-09-05",
  dateModified: "2026-09-05",
  author: { "@type": "Organization", name: "Threadly" },
};

const FAQ_ITEMS: [string, string][] = [
  [
    "What's the main difference between Bisonary and Threadly?",
    "Bisonary is a writing copilot: you find a post worth replying to yourself while browsing X, and it helps you draft a better reply in your own voice. Threadly does the finding for you — it scans X on a schedule for conversations matching your keywords, drafts a reply with AI grounded in that post, and puts it in an Approval Inbox for you to review. They overlap on AI-drafted replies, but Bisonary has no conversation-discovery feature at all.",
  ],
  [
    "Does Bisonary find conversations for me?",
    "No. Bisonary is explicit about this — it's a \"writing copilot,\" not a discovery tool. You still need to find the post worth replying to on your own; Bisonary's job starts once you've already found it. Threadly's core feature is doing that discovery step for you, on a schedule, in the background.",
  ],
  [
    "Does Threadly do everything Bisonary does?",
    "No. Threadly doesn't learn or match your personal writing voice, doesn't offer per-action credit pricing, and doesn't have Bisonary's in-composer tools like emoji shortcuts or text enhancement. If you specifically want a writing assistant for replies you find yourself, Bisonary is built for that. If you want the conversations found for you in the first place, that's Threadly.",
  ],
  [
    "Can I use both?",
    "Yes — they solve different halves of the same problem. Some users could use Threadly to surface conversations worth replying to, then use a voice-matching tool like Bisonary to help draft the actual wording, though this isn't a workflow Threadly has built or tested directly.",
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

export default function BisonaryAlternativePage() {
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
            Short answer: Bisonary is a writing copilot — it helps you draft a better reply, in
            your own voice, to a post you&apos;ve already found while browsing X. Threadly does
            the finding for you: it scans X on a schedule for conversations matching your
            keywords and drafts a reply with AI for you to approve.
          </strong>{" "}
          Neither tool auto-posts on your behalf — the real difference is what happens before
          you start writing. Here&apos;s exactly how they compare, feature by feature.
        </p>

        <h2>Feature-by-feature comparison</h2>
        <div className="compare-table-wrap">
          <table className="compare-table">
            <thead>
              <tr>
                <th></th>
                <th>Bisonary</th>
                <th>Threadly</th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON_ROWS.map(([label, bisonary, threadly]) => (
                <tr key={label}>
                  <th scope="row">{label}</th>
                  <td>{bisonary}</td>
                  <td>{threadly}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="table-note">
          Figures checked directly against{" "}
          <a href="https://www.bisonary.com/pricing" target="_blank" rel="noopener noreferrer">
            bisonary.com/pricing
          </a>{" "}
          and Threadly&apos;s own pricing as of {LAST_VERIFIED}.
        </p>

        <h2>Where Bisonary wins</h2>
        <p>
          If you already know which posts you want to reply to and the thing slowing you down
          is writing — matching your own voice, avoiding a generic AI tone, getting past a blank
          reply box — Bisonary is built specifically for that moment. Its voice-matching gets
          better the more you use it, and its in-composer tools (emoji shortcuts, quick text
          enhancement) are things Threadly doesn&apos;t offer at all.
        </p>

        <h2>Where Threadly wins</h2>
        <p>
          Bisonary has no discovery step — you still have to find the right conversation
          yourself by scrolling X. Threadly&apos;s core feature is finding it for you, on a
          schedule, without you needing to be browsing at all. If the bottleneck is knowing
          which conversations are even worth joining, Bisonary doesn&apos;t address that;
          Threadly is built around exactly that problem.
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
