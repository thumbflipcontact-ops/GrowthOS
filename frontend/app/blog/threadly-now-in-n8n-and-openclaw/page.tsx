import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

const TITLE = "Threadly Now Works Inside n8n and OpenClaw — Not Just Its Own Dashboard";
const DESCRIPTION =
  "Threadly's Approval Inbox now shows up wherever you already work: as an n8n community node, and as a ClawHub skill for OpenClaw agents. Same human-approval gate, two new places to use it.";

export const metadata = {
  title: `${TITLE} — Threadly`,
  description: DESCRIPTION,
  openGraph: { title: TITLE, description: DESCRIPTION, type: "article" },
};

const JSON_LD = {
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  headline: TITLE,
  description: DESCRIPTION,
  datePublished: "2026-08-18",
  author: { "@type": "Organization", name: "Threadly" },
};

export default function IntegrationsAnnouncementPost() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }}
      />
      <LandingNav />

      <article className="legal">
        <h1>{TITLE}</h1>
        <p className="updated">August 18, 2026 · Threadly Blog</p>

        <p>
          The whole premise of Threadly is that a human reads every reply before it posts. That
          only holds up if reviewing a draft is actually convenient — not one more dashboard to
          remember to check. So instead of asking you to come to Threadly, we&apos;ve started
          bringing Threadly to the tools you&apos;re probably already running.
        </p>

        <h2>n8n</h2>
        <p>
          <a href="https://www.npmjs.com/package/n8n-nodes-threadly" target="_blank" rel="noreferrer">
            n8n-nodes-threadly
          </a>{" "}
          is a community node for n8n. A trigger node fires whenever Threadly discovers a new
          relevant conversation on X — no polling, it registers a real webhook — and action
          nodes let a workflow list conversations, list drafts awaiting review, and approve or
          reject a specific draft. If you already have an n8n instance running your other
          automations, this lets Threadly&apos;s output land in the same place instead of a
          separate tab. Source and setup instructions are on{" "}
          <a href="https://github.com/thumbflipcontact-ops/n8n-nodes-threadly" target="_blank" rel="noreferrer">
            GitHub
          </a>
          .
        </p>

        <h2>OpenClaw</h2>
        <p>
          <a href="https://clawhub.ai/thumbflipcontact-ops/skills/threadly" target="_blank" rel="noreferrer">
            threadly
          </a>{" "}
          is a ClawHub skill for OpenClaw agents — the same set of operations (list
          conversations, list/approve/reject drafts, list published replies, manage webhook
          subscriptions), written as instructions an agent can follow directly. One thing we
          were deliberate about: the skill explicitly tells the agent to only approve or reject
          a draft when a human has instructed it to do so for that specific draft, in that
          conversation turn — never autonomously, never in a batch. An agent that can act on its
          own is exactly the case where the human-approval gate matters most, not least. Install
          it with <code>openclaw skills install @thumbflipcontact-ops/threadly</code>, or read
          the source on{" "}
          <a href="https://github.com/thumbflipcontact-ops/threadly-clawhub-skill" target="_blank" rel="noreferrer">
            GitHub
          </a>
          .
        </p>

        <h2>Same rule, more places to apply it</h2>
        <p>
          Neither integration changes what Threadly actually does: conversation discovery and
          reply drafting stay fully automated, and nothing posts under your account until you
          personally approve it. What changes is where you get to make that call — your n8n
          canvas, your OpenClaw agent, or Threadly&apos;s own Approval Inbox, whichever you
          already have open.
        </p>
        <p>
          <a href="/signup">Start a 7-day free trial</a> — no card required.
        </p>
      </article>

      <LandingFooter />
    </>
  );
}
