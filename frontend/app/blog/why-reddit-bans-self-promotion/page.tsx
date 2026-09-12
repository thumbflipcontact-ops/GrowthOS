import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

const TITLE = "Why Reddit Bans Self-Promoters (And What Actually Gets Through)";
const DESCRIPTION =
  "Reddit's self-promotion rules aren't arbitrary, and \"just be authentic\" isn't specific enough to follow. Here's what actually gets accounts banned, what moderators are really checking for, and what a comment that survives looks like.";

export const metadata = {
  title: `${TITLE} — Threadly`,
  description: DESCRIPTION,
  alternates: { canonical: "/blog/why-reddit-bans-self-promotion" },
  openGraph: { title: TITLE, description: DESCRIPTION, type: "article" },
};

const JSON_LD = {
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  headline: TITLE,
  description: DESCRIPTION,
  datePublished: "2026-09-10",
  author: { "@type": "Organization", name: "Threadly" },
};

export default function SelfPromotionRulesPost() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }}
      />
      <LandingNav />

      <article className="legal">
        <h1>{TITLE}</h1>
        <p className="updated">September 10, 2026 · Threadly Blog</p>

        <p>
          Most advice on Reddit self-promotion stops at &quot;be authentic&quot; or &quot;add
          value first,&quot; which is true and also useless, because it doesn&apos;t tell you
          what a moderator or the automod is actually checking when your comment gets removed
          twelve seconds after you post it. It wasn&apos;t a human reading your words and judging
          your character. It was a rule, and the rule has a shape you can learn.
        </p>

        <h2>The 9:1 ratio is the actual rule, not a suggestion</h2>
        <p>
          The unofficial but widely enforced norm across Reddit is that roughly nine out of every
          ten things you post should have nothing to do with anything you&apos;re promoting.
          Comment on other people&apos;s posts, answer questions in your area with no link
          attached, participate like an actual member of the subreddit for weeks before you ever
          mention your own thing. Accounts that show up, post something that reads like a pitch,
          and leave a trail of nothing else are exactly what the ratio exists to catch, and it
          catches them fast. This isn&apos;t about Reddit disliking marketing. It&apos;s about
          telling apart someone who&apos;s part of the community from someone using it as a
          distribution channel.
        </p>

        <h2>Account age and karma gates exist so a fresh account can&apos;t skip the line</h2>
        <p>
          Plenty of subreddits won&apos;t even let a low-karma or brand-new account post at all,
          automod deletes it before a human ever sees it. This is the most common way a first
          attempt fails, and it has nothing to do with what you wrote. If your account is new,
          the fix isn&apos;t a better comment. It&apos;s spending real time being a normal
          Redditor first: commenting, upvoting, existing in a few communities long enough that
          your account doesn&apos;t look like it was created for this one purpose.
        </p>

        <h2>Vote velocity and posting pattern are the tells that don&apos;t require reading a word</h2>
        <p>
          A moderator doesn&apos;t need to read your comment closely to suspect it. A handful of
          comments posted in quick succession across unrelated threads, all mentioning the same
          product, from an account with a posting history that starts the same week, is a pattern
          that&apos;s visible from the account page alone. So is a comment that gets an
          unnaturally fast vote spike right after posting. None of this requires anyone to parse
          your sentences. The shape of the behavior is the signal.
        </p>

        <h2>What actually gets through looks boring</h2>
        <p>
          The comments that survive and even get upvoted are the ones where the product mention
          is the smallest part of the comment, not the point of it. Someone asks a specific
          question, you answer the actual question first with real specificity, and only bring up
          what you built if it&apos;s a genuinely relevant next thing to mention, sometimes not
          even then. If you&apos;d be equally happy to post the comment with the product mention
          deleted, that&apos;s usually a sign it&apos;s going to read as genuine instead of
          bolted-on. If deleting your product mention would leave the comment empty, that&apos;s
          the tell that it was never really an answer.
        </p>

        <h2>This is why automation that posts on its own is the actual risk</h2>
        <p>
          Everything above is a pattern-matching problem, and pattern matching is exactly what
          catches tools that reply automatically at scale: consistent timing, consistent
          phrasing, a product mention that shows up whether or not it&apos;s relevant. A tool that
          finds conversations and drafts replies can genuinely save the time; a tool that also
          decides on its own when to post removes the one thing keeping each reply honestly
          specific to what it&apos;s replying to. That&apos;s the reason Threadly drafts a reply
          for every conversation it finds and then stops, every single one waits in your Approval
          Inbox until you personally read it and decide it&apos;s actually worth sending.
        </p>

        <p>
          <a href="/signup">Start a 7-day free trial</a> — no card required.
        </p>
      </article>

      <LandingFooter />
    </>
  );
}
