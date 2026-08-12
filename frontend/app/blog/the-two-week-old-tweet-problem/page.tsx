import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

const TITLE = "The 2-Week-Old Tweet Problem: Why Manual X Search Misses Your Best Leads";
const DESCRIPTION =
  "By the time you remember to search X again, the intent signal has already expired. Here's why manual search structurally can't keep pace, and what continuous, reviewed discovery looks like instead.";

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
  datePublished: "2026-08-12",
  author: { "@type": "Organization", name: "Threadly" },
};

export default function TwoWeekOldTweetPost() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }}
      />
      <LandingNav />

      <article className="legal">
        <h1>{TITLE}</h1>
        <p className="updated">August 12, 2026 · Threadly Blog</p>

        <p>
          Here&apos;s the usual routine: you remember you should be finding leads on X, so you
          search your keyword, skim the results, reply to two or three posts, and close the tab.
          A week or two later you do it again. It feels like you&apos;re covering the ground —
          but almost everything worth finding happened in the gap, not during the five minutes
          you were actually looking.
        </p>

        <h2>The decay curve of buying-intent tweets</h2>
        <p>
          A tweet where someone&apos;s actually describing the problem you solve isn&apos;t
          evergreen. It has a short window where replying is useful — while the person is still
          thinking about the problem, still checking notifications on that post, still open to a
          suggestion. Reply inside that window and you&apos;re part of the conversation. Reply
          after it, and by the time you find the post, the intent signal has already expired —
          the person moved on, solved it another way, or just stopped checking that thread. The
          tweet still exists. The opportunity attached to it doesn&apos;t.
        </p>

        <h2>Why manual search can&apos;t keep pace</h2>
        <p>
          The honest pattern for manual search is: search once, find two or three posts, move
          on, forget to search again for a week or two. Not because you&apos;re bad at this —
          because it&apos;s genuinely tedious to run the same search over and over, and there&apos;s
          no natural trigger to remind you. The gap between searches is exactly where the
          decay curve above does its damage. You&apos;re not missing leads because you&apos;re
          searching wrong. You&apos;re missing them because nobody can manually re-run a search
          every few hours, every day, forever.
        </p>

        <h2>What continuous, reviewed discovery looks like</h2>
        <p>
          The fix isn&apos;t searching harder — it&apos;s not needing to remember to search at
          all. A background process watching your keywords on a schedule closes the exact gap
          that kills manual search: it doesn&apos;t get bored, forget, or move on to other work.
          It just keeps checking. The part that stays yours is the judgment call on what to say —
          this isn&apos;t &quot;auto-reply to everything that matches,&quot; it&apos;s
          &quot;surface everything that matches, draft a starting point, let a human decide.&quot;
          Social listening that includes a review step, not social listening that skips straight
          to posting.
        </p>

        <h2>A worked example</h2>
        <p>
          Say your keyword is &quot;crawl budget.&quot; Someone posts asking why their site
          isn&apos;t getting indexed and mentions crawl budget by name. Threadly&apos;s
          conversation finder catches that post on its next scheduled pass — could be minutes
          after it went up, not whenever you next happen to search. Claude drafts a reply
          grounded in the actual post, not a template. That draft sits in your Approval Inbox.
          You read it, decide if it sounds like you, edit it if it doesn&apos;t, and approve it.
          The reply goes out while the conversation is still live, not two weeks later when
          you&apos;re doing your next manual sweep.
        </p>

        <h2>Stop losing the gap</h2>
        <p>
          If your current process is &quot;search when I remember to,&quot; the leads you&apos;re
          missing aren&apos;t the ones you never found — they&apos;re the ones you found too
          late. Continuous discovery closes exactly that gap.
        </p>
        <p>
          <a href="/signup">Start a 7-day free trial</a> — no card required.
        </p>
      </article>

      <LandingFooter />
    </>
  );
}
