import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

const TITLE = "How to Find Reddit Posts From People Who Actually Need What You Built";
const DESCRIPTION =
  "Searching Reddit for your product category mostly surfaces noise. The posts worth replying to use problem language, not category language — here's how to actually find them.";

export const metadata = {
  title: `${TITLE} — Threadly`,
  description: DESCRIPTION,
  alternates: { canonical: "/blog/finding-buying-intent-posts-on-reddit" },
  openGraph: { title: TITLE, description: DESCRIPTION, type: "article" },
};

const JSON_LD = {
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  headline: TITLE,
  description: DESCRIPTION,
  datePublished: "2026-09-11",
  author: { "@type": "Organization", name: "Threadly" },
};

export default function FindingBuyingIntentPost() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }}
      />
      <LandingNav />

      <article className="legal">
        <h1>{TITLE}</h1>
        <p className="updated">September 11, 2026 · Threadly Blog</p>

        <p>
          Search Reddit for the name of what you do and you&apos;ll get a wall of results, and
          almost none of them are useful. Someone mentioning a topic in passing, an old thread
          that&apos;s been dead for a year, a debate about the category that has nothing to do
          with anyone looking for a solution right now. The problem isn&apos;t that Reddit
          search is bad. It&apos;s that category words and buying-intent words are two different
          vocabularies, and most people search with the wrong one.
        </p>

        <h2>People don&apos;t describe their problem the way you describe your product</h2>
        <p>
          If you built an SEO tool, searching &quot;SEO&quot; gets you every SEO conversation
          that&apos;s ever happened, including thousands of people just discussing the topic. The
          person actually stuck and looking for help writes something closer to &quot;nobody&apos;s
          finding my site no matter what I try&quot; or &quot;my traffic fell off a cliff and I
          don&apos;t know why.&quot; They&apos;re not thinking in your category&apos;s vocabulary
          because they don&apos;t know your category&apos;s vocabulary. They&apos;re describing a
          problem in the plainest words they have. Search for the complaint, not the solution
          category, and the signal-to-noise ratio changes completely.
        </p>

        <h2>Questions beat statements, almost every time</h2>
        <p>
          A post that states an opinion about a topic is a conversation. A post that asks a
          question is an opening. &quot;What do people use for X&quot;, &quot;is there a way to
          do Y&quot;, &quot;how do you all handle Z&quot; are the shapes of a post where a genuine,
          specific answer is welcome by definition, the person asked for exactly that. Filtering
          for question-shaped posts before you even read them cuts out most of the noise before
          you&apos;ve spent any time on it.
        </p>

        <h2>Recency matters more than it seems like it should</h2>
        <p>
          A perfectly relevant thread from eight months ago is close to worthless. The person who
          posted it either solved their problem, gave up, or stopped checking that thread weeks
          ago. Reddit&apos;s own sort-by-new and the recency filter exist for exactly this reason,
          and it&apos;s worth defaulting to a short lookback window rather than a wide one, even
          though the wide one turns up more results. More old results isn&apos;t more
          opportunity. It&apos;s more time spent reading threads nobody&apos;s going to see your
          reply in.
        </p>

        <h2>The subreddit tells you more than the keyword does</h2>
        <p>
          The same sentence means something different depending on where it&apos;s posted. &quot;I
          need something to handle this&quot; in a subreddit for professionals in your exact
          space is a much stronger signal than the identical sentence in a huge general-interest
          subreddit, where it&apos;s more likely to be a passing comment in an unrelated thread.
          Building a short list of the five or six subreddits where your actual audience already
          hangs out, and weighting matches from those higher than matches from everywhere else,
          does more for result quality than almost any keyword tweak.
        </p>

        <h2>The real filter is buying intent, not topic match</h2>
        <p>
          A thread that mentions your category isn&apos;t the same as a thread from someone who
          wants a solution today. &quot;I&apos;ve been thinking about trying X&quot; and
          &quot;does anyone actually recommend a good X, I&apos;m done doing this manually&quot;
          share half their vocabulary and mean completely different things. This is the part
          that&apos;s genuinely hard to do by hand at any volume, reading a hundred keyword
          matches to find the six that are real intent doesn&apos;t scale past a few searches a
          week before it stops being worth your time. It&apos;s the actual reason Threadly has an
          LLM read every match before saving it as a lead, not just count whether the keywords
          showed up. A keyword match tells you the topic came up. It doesn&apos;t tell you
          whether the person&apos;s actually looking.
        </p>

        <p>
          <a href="/signup">Start a 7-day free trial</a> — no card required.
        </p>
      </article>

      <LandingFooter />
    </>
  );
}
