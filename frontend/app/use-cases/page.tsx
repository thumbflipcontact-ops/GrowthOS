import { LandingFooter } from "@/components/LandingFooter";
import { LandingNav } from "@/components/LandingNav";

export const metadata = {
  title: "Use Cases — Threadly",
  description:
    "Who Threadly is for: founders, indie hackers, and small teams finding real conversations about the problem they solve, on X.",
};

const USE_CASES = [
  {
    title: "Launching a new product",
    body: "The people who need what you're building are already describing the problem on X, right now. Threadly finds those conversations instead of you scrolling search results all day.",
  },
  {
    title: "Customer discovery, without the guesswork",
    body: "See real people talking about the problem you solve — in their own words — before you spend another week building based on a guess.",
  },
  {
    title: "Staying visible without it becoming a full-time job",
    body: "Solo founders don't have hours a day for social listening. Threadly keeps watching your keywords on a schedule, so you only spend time on the replies worth sending.",
  },
  {
    title: "Not losing track of who you've already talked to",
    body: "Every conversation Threadly finds and every draft you approve lives in one place — no more digging through your own X history trying to remember who you already replied to.",
  },
  {
    title: "Picking up new conversations as they happen",
    body: "Your keywords don't go stale — Threadly keeps searching, so you catch new conversations without re-running the same searches yourself every few days.",
  },
  {
    title: "Small teams doing their own growth",
    body: "No dedicated growth hire yet. Threadly gives one person the reach of manually monitoring X all day, in the time it takes to review a few drafts.",
  },
];

export default function UseCasesPage() {
  return (
    <>
      <LandingNav />

      <header className="hero">
        <span className="hero-badge">
          <span className="dot" /> Who Threadly is for
        </span>
        <h1>Built for people finding their first users, not managing a social team.</h1>
        <p className="lead">
          If you&apos;re a founder, indie hacker, or small team trying to find the people already
          talking about the problem you solve on X, this is what Threadly does for you.
        </p>
        <div className="hero-ctas">
          <a href="/signup" className="btn btn-grad">
            Start your 7-day free trial
          </a>
          <a href="/features" className="btn-ghost">
            See all features
          </a>
        </div>
      </header>

      <section className="landing-section">
        <div className="feature-grid">
          {USE_CASES.map((useCase) => (
            <div className="step-card" key={useCase.title}>
              <h3>{useCase.title}</h3>
              <p>{useCase.body}</p>
            </div>
          ))}
        </div>
      </section>

      <LandingFooter />
    </>
  );
}
